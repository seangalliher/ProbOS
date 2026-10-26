# AD-1341 S4: the lessons format, and the stand-down that gives each crew agent one bounded turn to leave exit notes for its successor

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26

**Header edits (orchestrator, 2026-10-26, mechanical; no pair, SEARCH or REPLACE changed):** the **Base** paragraph (S3 merged: base `origin/main` `20c1ec00`), section 4's "Expected focused counts" paragraph (measured on that base) and its tests-first sentence, and section 6's names of each new test file's first failing import (each leg was run on the oracle); after A2, section 14 property 1's per-section bound (A2 made the lesson's bound 700 characters in all, property 14).

**Amendment A5:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from round 3 of the three cross-family reviews of the committed head `bbc64351` (9 findings; one P1, found by two reviewers) and the round-three brake (continue; round 4 a delta review by two reviewers). The strict read gets one table of every filesystem operation it makes, with one disposition each (7.3a, O1 to O7), and a trace-and-fault test that fails for an operation without a row (C3g). `_markdown_files_or_raise` walks with `os.scandir` and raises every `OSError` except a missing root's (R3-M1-1: `os.walk` took an entry whose type it could not read for a file). It returns files only, so a listed file whose read fails raises without A2's second look through `Path.is_file()`, which reads EBADF, ENOENT and "the device is not ready" as "not there" (O5). The citation read raises for a listed ship-wide note its second read cannot find (O6). The stand-down's two existence checks ask `Path.lstat` and treat "cannot tell" as unknown (O7). A stored frontmatter value `str()` cannot convert is archived as no value, at the exit note's three conversions and S1's six (R3-M1-2). The console counts completed writes and, apart, the writes that may have left a note (M2-2). A first read that returns after the window refuses before any turn task exists (M2-3). `_left_at`'s unknown branch has its test and rows (M2-4). M2-1 (reach reclassified to injected-only), R3-M1-3 and M2-5 are registered (R28 to R30); R31 lists what stays outside the table. 7.3 gains pairs 8 and 9 (37 pairs in all). Milestone boundaries are unchanged.

**Amendment A4:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from round 2 of the three cross-family reviews of the repaired head `e1e97d25` (16 findings, two P1 with one root). The strict listing now raises for a directory it cannot list (7.3a pairs 3 to 5: an error-reporting walk for `strict=True` only; the default runs the same `rglob` call). A section name matches in ASCII only, so a lookalike letter opens no section instead of raising; a lesson refuses every C0 and C1 control and DEL but tab, line feed and carriage return; `is_exit_note_text` refuses `---`, where Ship's Records cuts a frontmatter value (register R25), and the stand-down offers only episodes whose ids it admits. The stand-down's write path is made smaller, not larger: it never removes a document (A2's rollback could delete another writer's document and could not run on cancellation), checks for a note written meanwhile without an await and charges that check to the window, begins no write once the window has closed, and reports the path of any note a failed or cut-off write left. `asyncio.create_task` replaces `ensure_future`. M3 is unchanged.

**Amendment A3:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from the orchestrator's run of A2 on the oracle (151 of the 154 cases of the three new files passed, and every focused list passed except X8's three cases): X8 builds its own transport that answers as a served app does (`raise_app_exceptions=False`) and records the one exception the app raised, because the shared `_client` re-raises the app's exception instead of returning the 500 (C108 to C110); R19 records that M3-F2 is already F-141 on #1523 and is not re-filed (C111: the Architect withdrew its A2 ruling "file it as its own BF" after the orchestrator found F-141 in the register). No other text changes.

**Amendment A3 (2):** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from the orchestrator's stress run of A3 on the oracle `312a792c` (S4c `[write]` failed 21 of 60 repetitions; every other case passed all 8 runs of the file). asyncio fires a timer once the loop's clock is within one clock resolution of it (15.6 ms on Windows before Python 3.13), so the hanging write's bound could expire just before the deadline the service reads from the same clock, and the queued turn began a write. The service is unchanged: that write is still bounded by the window and removed. S4c `[write]` and S3c (the same race on the recall's bound) now run on the stand-down's injected `clock`, and S4c records a write when `write_entry` is called, which D-23 needs (C116, C118 to C120); S3 and S4b keep their real bound, now 1.5 s with 1 s of headroom (C115, C117, C121). Test functions and cases are unchanged.

**Amendment A1:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from the orchestrator's dry run of A0 on the S3 candidate `60e4415e`: all 26 pairs applied once; M2 and M3 passed; M1 failed one hidden pin, S1's import census of `archive_promotion.py` (7.4a now updates it). A1 also renames the lesson class to `LessonLearned` (a `Lesson` already exists, `evolution_store.py:73`), records the phantom triage (§12), names BF-939 (#1683) and S3's register R11 and R13 (§0, D16, register R16, R17), and hardens four things S3's round 1 taught: the citation read skips a document the promotion skips (C3c, P-12), the refusal precedes the attachment unlink and the audit marking (X1b, E-5, E-6), the write lock has a test (S6b, D-17), and every refusal and control asserts its own text or premise (S11, X5, X7).

**Status:** build-ready. Slice 4 of 6 of #1569; it does not complete the issue. No new AD or BF number. **Base:** `origin/main` `20c1ec00` (S3 merged as PR #1684; tree `c382d42c5daf0e32f445bb982e4cf4b162f4210e`); the orchestrator re-verified all 27 pairs on it by tool on 2026-10-26 (zero failures). A0 was drafted on the S3 oracle `fefd7f79`; A1 re-verified every anchor on S3's repaired head `60e4415e` (**S3 anchors this contract depends on**). Every SEARCH below anchors on text S3 does not touch, except the two listed in **S3 anchors this contract depends on** (after §11). The orchestrator re-verifies every SEARCH on the real post-S3 merge before any Builder starts; a changed anchor comes back to the Architect. **Captain:** nothing in this slice meets a Captain condition (D18). One decision (D12, chain-of-command review moves to S5) is the Captain's to overrule.

**Milestones and tiers:** M1 the lessons format and the exit note's promotion (**HIGH**: crew-authored text and citations into the Ship's Archive); M2 the stand-down (**HIGH**: it produces the crew-authored text and the citations); M3 the AD-754 window for notes not yet archived (**HIGH**: erasure, privacy); M4 trackers. Each milestone is one Builder delegation and one local commit, built in order. The broad gate is the orchestrator's single canonical run, once, after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1341-s4 --receipt logs/gates/ad1341-s4.receipt.json`. The Builder runs only the focused gates in §4. Review: cross-family (`gpt-6.1-sol`) for M1, M2 and M3 (D17). One mutation campaign, on the assembled tree (§10).

**Amendment A2:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from round 1 of the three cross-family reviews of the candidate `54cb4027` (24 findings, four P1). Three shared contracts change, each at its smallest seam: `RecordsStore.list_entries` gains a keyword-only `strict` (7.3a), so the AD-754 read and the stand-down's first read fail closed on a note file that exists but cannot be read now (M1-F1, M3-F1); `CognitiveAgent._conversational_agentic_will_run` answers no for a `direct_message` carrying `bounded_turn: True`, so a stand-down turn is answered inline on the single-pass path and never promoted into a background work item (7.9a, M2-1); the Oracle tool is not touched, and a lesson is bounded at 700 characters in all, so a whole archived note fits one tool entry (M1-F4, L6 through the real tool). A2 also closes the format under rendering (M1-F3), archives exactly the canonical note (M1-F5), checks every provenance value the origin line and SQLite receive (M1-F2, F6, F7, M2-7), recognises `_` emphasis (M1-F8), corrects the plan's docstring (M1-F9), rebuilds the stand-down's bounds (one window from before the first read through every write, one deadline per turn, one turn per billet, a failed write removed, a member's fault kept inside its turn, no turn outliving the call: M2-2 to M2-6), budgets excerpts in transport bytes (M2-8), and strengthens S3, S4b, S9, S13b, S14, X1, X2 and X7 (M2-9, M3-F3 to F5). Two pre-existing findings are registered, not repaired (R18, R19). Milestone boundaries are unchanged; 7.3a is in M1 and 7.9a in M2.

**Tests:** new `tests/test_ad1341_s4_lessons.py` (M1: 30 functions; A4 added six, A5 five), `tests/test_ad1341_s4_stand_down.py` (M2: 37 functions; A4 added five, A5 four), `tests/test_ad1341_s4_exit_note_erasure.py` (M3: 10 functions; A5 parametrises X8 by fault). Updated: `tests/test_ad1341_s1_archive_store.py` (M1: the closed `SourceKind` set) and `tests/test_ad1341_s1_promotion.py` (M1, A1: the service's import set), each with an inline reason.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| `probos reset` is offline: a synchronous command that holds the AD-816 pidfile and refuses while a vessel owns the data directory, so no agent can take a turn inside it (#1569 comment 2, P1) | present | `__main__.py:2905`, `:2987-3002` |
| A tier 2 reset deletes every episode with the crew (`chroma.sqlite3`, `episode_archive.db`, the ChromaDB directories) and keeps `ship-records/`; tier 3 deletes `ship-records/` | present | `__main__.py:2642-2678` |
| S1's promotion reads Ship's Records only; a document is a source by its path and frontmatter (`source_kind_for`), read as the anonymous reader, withheld below `ship` (C1); `SourceKind` is closed and has no episode member | present | `archive_promotion.py:37-69`, `:105-150`; `archive_store.py:93-102` |
| A record's `timeline_id` is the promoting reset's; Ship's Records carry no episode ids, so no `src` producer writes a non-empty `source_episode_ids` | present | `archive_promotion.py:13-14`, `:133-148`; S3 Absence S3-AV4 |
| S3's review reads the plan (`review_promotion`, `probos archive pending`) and the Captain vetoes a source by its records path (`probos archive veto`); both work while a vessel runs (no pidfile) | present (S3) | `archive_promotion.py:204-213`; `__main__.py:3430-3564` |
| S3's AD-754 check refuses an erasure while an archive entry cites a matched episode; it reads the archive only | present (S3) | `erasure.py:88-113`, `:151`, `:187`, `:202`; `routers/security.py:89-121` |
| S3 A2: `entry_ids_citing` raises `ValueError` for any citation cell that is not a JSON list of strings (`_CITING_SQL` skips only `'[]'`, so NULL and empty cells are fetched). S4 never calls it. S4's archived cells are `promote_entry`'s `json.dumps(list[str])`, which S3's read answers (S15). S3's check runs before S4's at every entry point, so an unreadable cell stops a single-episode erasure there, and a cascade records it per episode, as S3 left it | present (S3) | `archive_store.py:338`, `:654-679`; `erasure.py:111`, `:151`, `:249-258` |
| S3's citation check reads every citing row once per call, and a cascade makes N+1 calls (S3 register R13: 28.5 s for 1,000 matches against 10,000 citing entries). S4's check adds no read per episode: one Ship's Records read per request, then a mapping lookup | present (S3); scheduled to S5 (register R17) | `erasure.py:102-113`, `:151`, `:187`, `:202` |
| **BF-939 (#1683), open:** an AD-754 erasure unlinks each attachment of the erased episode without asking whether another episode shares the content-addressed blob (S3 register R11). S4 neither depends on it nor worsens it; it must land before S5 (register R16) | open defect | `erasure.py:152-153`, `:331-339` |
| The Captain's 1:1 message to an agent is a `direct_message` intent sent through `runtime.intent_bus.send`; the reply body is `DmReply.from_intent_result(result).body` | present | `experience/commands/session.py:110-148`; `channels/base.py:452-457`; `dm_reply.py:898-912` |
| A2: a 1:1 `direct_message` is the conversational agentic (tool-calling) loop's turn when `dm_agentic.enabled`, and a run past `promote_to_task_after_seconds` returns an acknowledgement and keeps running as a background work item (AD-1165, BF-705); the shipped config enables both (40 s). `_conversational_agentic_will_run` is the one gate | present (found by M2's round 1, M2-1) | `config/system.yaml:469-470`, `:624`; `cognitive_agent.py:4692-4715`, `:4754`, `:5190-5205`, `:5404` |
| A2: `RecordsStore.list_entries` catches every read or parse failure of a listed file and skips it; `write_entry` publishes the file before git runs | present (M1-F1, M3-F1, M2-4) | `records_store.py:977-987`, `:321-326`, `:1239-1262` |
| A bounded agent turn has precedent: System QA wraps `agent.handle_intent` in `asyncio.wait_for` with a per-test and a total timeout | present | `agents/system_qa.py:318-334` |
| Slash commands run in the console shell and, through `api._handle_slash_command`, from the HXI chat and the channel adapters; `_BLOCKED_COMMANDS` keeps a command at the console | present | `experience/shell.py:63-125`, `:254-347`; `api.py:45-109`; `channels/base.py:367-370` |
| No CLI subcommand calls a running vessel's API | present | Absence S4-AV2 |
| The crew and their identities: `runtime.registry.all()`, `crew_utils.is_crew_agent(agent, ontology)`, `runtime.identity_service.resolve(slot_id)` → `IdentityRef` (did, callsign, sovereign id) | present | `runtime.py:684`, `:1237`, `:2874`; `crew_utils.py:69-76`; `identity_service.py:35-63`, `:79-95` |
| An agent's recent episodes: `EpisodicMemory.recent_for_agent(agent_id, k)` (sovereign shard; reads the whole collection, then filters) | present | `cognitive/episodic.py:4109-4134` |
| The vessel's timeline at runtime is `ontology.get_vessel_identity().instance_id` (`"unknown"` when none is loaded); S2 attaches the same id to the Oracle | present | `ontology/service.py:86-92`; `runtime.py:3428` |
| Ship's Records: `write_entry(author, path, content, message, *, classification, status, topic, tags, extra_frontmatter)` replaces a document in place; `read_entry` returns its stripped body; `list_entries(directory)` | present | `records_store.py:211-319`, `:930-1001`, `:1190-1200` |
| LLM governance: AD-636 caps concurrent model calls at 6 with 2 reserved for interactive calls; AD-617b's per-agent hourly cap is off by default | present | `config_models/knowledge.py:238-258` |
| The live archive is schema v1 with 0 rows and 0 generations (2026-10-26) | taken as given | #1569 comment 13; not read here (§Not verified, item 1) |

## 1. Problem

#1569 Decision item 3: "Before a reset of tier 2 or higher, each crew agent gets a bounded, scheduled turn to write exit notes for its successor: what it learned, what it would do differently, what remains open. The notes are archived with the author's DID and callsign. Writing them is optional, and the window is bounded so a reset is never blocked by an agent." Comment 1 adds the format: Observation, Discussion, Lesson, Recommendation. Acceptance: "The exit-notes window gives each agent one bounded turn, archives what it writes, and lets the reset continue when the time runs out or an agent writes nothing", and "No raw episode is ever written to the archive."

Three things are missing:

1. **No turn.** `probos reset` runs with the vessel stopped (P1), so nothing can ask an agent anything inside it. No live step before it exists.
2. **No lesson source.** S1's sources are reports, the Captain's log and notebook findings. Nothing carries an agent's DID or the episodes it cites into the archive. The first non-empty `source_episode_ids` will come from this slice.
3. **A citation window.** S3's AD-754 check reads the archive. A note written before the reset and archived at the reset sits in Ship's Records in between. An erasure in that gap would leave the reset to archive a note citing an erased episode.

## 2. Solution overview

- **M1, the format and the promotion.** A new `knowledge/lessons.py` holds the one parser and the one renderer of the four sections, the citation reader and the exit note's path, origin line and envelope names. `SourceKind` gains `EXIT_NOTE`. S1's promotion treats `exit-notes/` as a source with its own rule (`_exit_note_record`). The rule checks the envelope, path, author, origin line, format and classification, attributes the entry to the timeline that wrote the note, and carries the author's DID, agent type and cited episode ids. A bad note is withheld, never raised. `exit_note_citations` is the AD-754 read of what the next promotion would archive, using the same rule and S3's `source_state`.
- **M2, the stand-down.** A new `probos/stand_down.py` service and a console command, `/stand-down`. Each crew agent gets one Captain's message through the intent bus, showing it its own most recent episodes by handle. Each turn and the whole window are bounded, and at most two turns run at once. A reply in the format is written to Ship's Records at `exit-notes/{timeline}/{agent_type}.md`; anything else writes nothing. `/stand-down` cannot be run from the HXI chat or the channel adapters.
- **M3, the window.** The `/forget` route reads the pending notes' citations once. `ErasureManager` refuses (409 `exit_notes_cite_erased_episodes`, with the paths) while one cites a matched episode. The Captain vetoes the note with S3's `probos archive veto` and retries.
- **M4.** Trackers.

`probos reset` does not change. It already promotes before it wipes, and it now promotes the notes as well. No schema change, flag, config field, event type or API route.

## 3. Decisions

- **D1 (premises).** §0. S1's decisions (D7 marker, D8 criteria, D12 pidfile, D16 lock), S2's label and S3's review, veto and citation check stand.
- **D2 (the trigger and its surface).** Ranked:
  - **(A) chosen: `/stand-down`, a slash command at the running vessel's console** (`probos serve --interactive`, as the Captain runs it, and the REPL). The Captain types it before stopping the vessel for `probos reset`. With no vessel running there is nothing to type it into: a reset without a stand-down resets exactly as before, and `probos reset` stays valid and unchanged for a Captain who skips it.
  - (B) `probos stand-down` as an offline CLI that calls the vessel: rejected. No CLI subcommand talks to a running vessel (Absence S4-AV2). It would need a new authenticated API route.
  - (C) a flag on `probos reset`: rejected. The reset runs with the vessel stopped (P1), so no agent can take a turn.
  - (D) an HXI route or button: deferred. `_handle_slash_command` also serves the HXI chat and the channel adapters, which have no Captain authentication beyond a channel allow list, and a stand-down spends a model turn per crew agent for minutes. `/stand-down` joins `_BLOCKED_COMMANDS` (register R6).
- **D3 (the turn).** Ranked:
  - **(A) chosen: the Captain's message.** A `direct_message` intent `{"text": prompt, "from": "captain", "session": False, "bounded_turn": True}` through `runtime.intent_bus.send`, as `channels/base.py:452-457` sends one, so the agent's own cognition answers. **A2 (M2-1):** `bounded_turn` marks a turn its sender bounds and cancels. `CognitiveAgent._conversational_agentic_will_run` answers no for it (7.9a), so the agent answers on its single-pass path, inline, and the DM consumer's tool-calling loop and its AD-1165 promotion into a background work item (shipped on: `dm_agentic.enabled`, 40 s) never run for it. Without it, a turn past 40 s came back as an acknowledgement while its model calls ran on outside the window (the reviewer's probe on the real consumer). Ranked: (a) chosen, an intent param that the one gate honours; (b) treat an acknowledgement as a pending turn: rejected, the run still outlives the window; (c) call `handle_intent` or the model below the bus: rejected, it bypasses the bus's authorization and AD-1343 gates; (d) a new intent: rejected, as (B) below; (e) change `dm_agentic` for the stand-down: rejected, global state for every DM. Services run the loop and the crew hold the judgment (AD-1299, AD-1336). The bus's own gates apply: a refusal or a stopped agent returns no turn.
  - (B) a new `exit_notes` intent handled in `CognitiveAgent`: rejected. Agent-side chain changes for one turn per generation.
  - (C) the service calls the model itself in the agent's name: rejected. That is not the agent's judgment and bypasses its standing orders and character.
  - (D) AD-1347 agent work items, (E) the duty schedule or the proactive loop, (F) a Ward Room DM thread: rejected. Each is claimed or fired on its own cadence (`duty_schedule.py:4`, `:173-197`; `agent_work.py:1-24`), and none can bound a window that ends at a reset. The issue named the duty schedule; a cron duty cannot be started by the Captain's order and cannot bound its own end.
- **D4 (what the agent is asked).** `exit_notes_prompt` (7.6), fixed in code and pinned by S9. It says why it asks (the successor will not share the agent's memories), what to write (what it learned, what it would do differently, what remains open), that writing is optional (reply `NO NOTES` and nothing is recorded), the exact format and its bound, the optional `Cites:` line, and where the note goes: Ship's Records under its callsign and DID, the Captain's review and veto, then the Ship's Archive, where every later crew reads it labelled as inherited. It tells the agent to write nothing it would not share with the whole ship, to summarise and not quote its memories, and to reply without tools, which holds by construction since A2 (D3: no tool-calling loop runs for a bounded turn). It shows the agent at most 12 of its own most recent episodes, each as a handle (`e1`..), a date and an excerpt of at most 160 bytes once JSON-escaped (160 ASCII characters, 26 CJK, 13 astral), so the message stays inside the 4 KiB standard for inline `IntentMessage.params` in any script (A2, M2-8; S7c).
- **D5 (the bounds).** `STAND_DOWN_TURN_SECONDS = 180.0` per turn (the Captain's own 1:1 messages use a 60-second TTL, `session.py:119`). `STAND_DOWN_WINDOW_SECONDS = 900.0` for the whole stand-down. `STAND_DOWN_CONCURRENCY = 2` turns at once, inside AD-636's 6 concurrent model calls. A turn past its bound is cancelled through `asyncio.wait_for`, as System QA's are. **A2:** each turn has one deadline, 180 s from its start and never past the window, that its recall and its ask both spend and that its reply must meet, so a reply that suppresses its cancellation and returns late writes nothing (M2-5). The window starts before Ship's Records is first read and bounds every write: a first read that cannot finish in time refuses the stand-down with nobody asked (M2-2). **A4:** no write begins once the window has closed, and the check for a note written meanwhile (no await) is charged to the window before it; the stand-down never removes a document, so a write that fails or that the window cuts off after publishing is reported with the path of the note it left, and a write that returns late (synchronous I/O, R22) is `written`, which it is (M2-4). A reply that arrives after the window writes nothing. An agent whose turn has not begun when the window closes is not asked (`not_reached`). The stand-down returns by the end of the window plus cancellation. A slow episode read is bounded by the same turn limit; a failed one offers no episodes. Module constants, not configuration (register R7). Tested: S3 (turn), S4 (window, late reply, not reached), S4b (the window bounds a turn its own bound would allow), S6 (concurrency), S7 (12 episodes, 160 characters); A2: S3b and S3c (one deadline per turn), S4c (the records stages), S7c (bytes), S7d (no fault or turn escapes its member or the call); A4: S2b (what a failed write leaves), S4d (the real clock), S4e (a cancelled stand-down).
- **D6 (the format, and where it is validated).** Four sections, in order, each once, each non-empty, together at most 700 characters (A2; A0 said 1,200 each). The Oracle tool cuts each entry to 1,200 characters (`oracle_query_tool.py:71`, `_cap_entry` `:119-129`), so at 1,200 a section a full note reached a later crew as its Observation alone (M1-F4). With the callsign, agent type and timeline bounded at 32, 48 and 64 characters, a whole archived note with the tool's marker, S2's longest label, the `[exit_note]` title and the origin line takes at most 1,172 characters of that entry (L6, through the real tool), far inside AD-1148's 6,000. The passive Oracle context previews 300 characters of every archive entry, of every kind (`oracle_service.py:763`; register R21). **Closed under rendering (A2, M1-F3):** a section whose text would read as a heading or a `Cites:` line once rendered on its own line is refused, so every accepted lesson renders to text that parses back to itself (L1b). Text with a NUL or a lone surrogate is refused (SQLite cannot store it whole). Headings may be `## Observation`, `**Observation**`, a bare `Observation` line or `Observation: text`. A label needs its colon, so "Lesson learned, ..." stays text. Text before the first heading is dropped. A `Cites:` line is read separately and never kept. **One parser** (`parse_lesson`) reads the agent's reply at the stand-down and the stored note at the promotion, and `LessonLearned.render` writes the canonical form, which parses back to itself (L1). A reply not in the format writes nothing (`not_in_format`).
- **D7 (where a note waits for the reset).** Ranked:
  - **(A) chosen: a Ship's Records document** at `exit-notes/{timeline}/{agent_type}.md`. The body is a fixed origin line ("Exit notes left by {callsign} ({agent_type}) of the crew of timeline {timeline} for their successor. A record, not a memory.") followed by the rendered lesson. The frontmatter has `author` (the callsign), `classification: ship`, `status: submitted`, `topic`, `tags`, and the envelope `exit_note: {version, timeline_id, callsign, agent_type, author_did, source_episode_ids}`. S1's promotion already reads Ship's Records, and S3's `pending` and `veto` already work by records path, so the Captain reviews and vetoes notes with the tools that exist. The path is keyed by agent type, not callsign, because callsigns repeat across generations (S2's RS2-3).
  - (B) a notebook entry (`notebooks/{callsign}/exit-notes.md`): rejected. Notebooks default to `private`, and S1's notebook criterion needs a `claim_id` or `published`. Exit notes would be mixed with an agent's working notes.
  - (C) a new store under the registry rules: rejected. A new `.db`, a baseline row and backup coverage, and the promotion would need a second reader. Nothing gained.
  - (D) promote straight into the archive at the stand-down: rejected. It skips S3's review, adds an archive writer that runs inside the vessel (S3's R3 race), and breaks S1's rule that the reset promotes before wiping.
- **D8 (classification).** `ship`. A note is written for the next crew, and C1 admits `ship` to the archive. Not `fleet`: fleet sharing is not built. Not narrower: C1 would withhold it, and the note exists to be inherited.
- **D9 (provenance and citations).**
  - The author's DID, callsign and agent type come from `IdentityService.resolve(slot_id)` (AD-441, AD-1346's one resolver). An agent without a DID or callsign, or whose callsign, agent type or DID could not stand in the note's origin line and envelope (`exit_note_provenance_ok`: one line, no control character, storable, within its bound), is not asked (`no_identity`; A2, M2-7).
  - Citations are the handles the agent names in its `Cites:` line, mapped to the episodes it was shown. Any other handle is dropped, and a note cites at most 12 distinct ids. So a note can cite only the agent's own recent episodes, and never an id it typed.
  - The service never copies an episode's text into a note. The note is the origin line plus the lesson the agent wrote. S1 shows an agent's words may restate what it remembers, and the prompt says to summarise, not quote.
  - The entry is attributed to **the timeline that wrote the note** (the envelope's), not the reset that promotes it. A note left by a skipped promotion is promoted at a later reset and still labelled as the generation that wrote it (P1, P3).
- **D10 (what reaches the archive, and when).** At the reset's promotion, under S1's rule: `probos reset` promotes before it wipes, and its plan now includes `exit-notes/` documents. The dry run lists them, and S3's `pending` shows each note's state. A note that breaks the rule is withheld and reported, never raised, so one bad note cannot stop a reset (S1 A3's lesson). A2 (M1-F2, M1-F6): the rule checks every text value SQLite stores, so a value it cannot encode is withheld, not raised in `promote_entry`; and the archived body is exactly the canonical note the Captain reviewed (M1-F5). The record carries `source_episode_ids`: the first non-empty citations in the archive.
- **D11 (idempotence).** A note already present at its path in this timeline is never overwritten. A2 (M2-3): nor by a turn of the same stand-down. The first crew agent of an agent type in crew order takes its billet's turn and a second is `duplicate`, not asked (register R9); a member listed twice is asked once; a note written by anyone after the stand-down began is found under the write lock and kept (`already_written`). A second `/stand-down` in one generation asks only the agents without a note (`already_written` for the rest), so a stand-down cut short by its window can be finished without asking anyone twice. S1's key `(kind, ref, sha256)` makes a second promotion of an unchanged note PRESENT under any timeline (P3).
- **D12 (does a lesson need approval, and who approves).** Ranked by what stays in the delegated-authority envelope:
  - **(A) chosen: opt-out review by the Captain, as S3 built it.** `probos archive pending` lists each note before the reset, the note is a readable Markdown file, and `probos archive veto PATH --reason TEXT` keeps one out. S1's default (promote before the reset) is unchanged. The Captain sits at the top of the chain of command, so the issue's "review before canon" holds at its last stage. No new control, flag or schema.
  - (B) chain-of-command review (#1569 comment 1, item 3: the department chief, then the Counselor or XO): **moved to S5**, with the after-action reports. There, lessons arrive continuously and a review step has a natural home (a dream step or duty). Inside a stand-down it would double the model turns in a bounded window whose reviewers are themselves writing their own notes, and a review not finished when the window closes would block or lose the note. **The Captain may overrule** this ordering. It moves a review stage the Captain asked for to the next slice; it does not weaken a control (register R1).
  - (C) opt-in approval behind a default-off flag (S3's D2 B): rejected for S4. A flag nobody turns on is dead code. With it on, a `--full` reset would delete unapproved notes with Ship's Records, because S6's snapshot is not built (S3's D2 B reason).
- **D13 (the Captain's controls).** `/stand-down` reports each agent's outcome and its note's path, then the next steps (`probos archive pending`; `probos archive veto PATH --reason TEXT`; stop the vessel; `probos reset`). Notes are read as files under `ship-records/exit-notes/{timeline}/`. A veto is S3's: content-free, permanent, honoured by the promotion with any content.
- **D14 (the AD-754 window).** Ranked:
  - **(A) chosen: refuse while a pending note cites a matched episode.** The `/forget` route reads `exit_note_citations` once per request, before anything is erased. A2 (M1-F1, M3-F1): that read lists Ship's Records strictly, so a note file that exists but cannot be read now raises (500, nothing erased) instead of being skipped as if absent. A note counts while S3's `source_state` says the next promotion would archive it (CREATED). A vetoed, erased or already archived note does not count; an already archived one is S3's own check. `ErasureManager` raises `ExitNotesBlockErasure(paths)` before anything is erased (a single episode, before its attachments; a scan, at the top of `_forget_all`), and the route answers 409 with the paths. The Captain vetoes each note and retries. Same shape as S3's D8: nothing is erased silently, and the open route gains no writer.
  - (B) withhold, at the reset, a note citing an erased episode, found through the eviction audit (`eviction_audit.db`, disposition `erased`): rejected. The audit's writes are best-effort (`eviction_audit.py:152-180` swallows a failure) and the audit can be disabled (`config.memory.eviction_audit_enabled`), so the guarantee would rest on a log that may not hold the row.
  - (C) the erasure rewrites or deletes the note: rejected. Ship's Records are the crew's documents. AD-754 never edits them (S3 D9), and the open route would gain a writer.
- **D15 (the Oracle).** Unchanged. An archived note reads S2's label first, then the origin line and the four sections. Ship's Records keep notes across a tier 2 reset, so a later crew's records tier (keyword search) can also return a note unlabelled by S2. The origin line says whose it is and that it is "A record, not a memory" (register R5; S2's RS2-6 is the general gap).
- **D16 (S3's register items, and which S4 owns).**
  - **S3 R2 (archive enabled but unavailable): owned for notes.** With the archive enabled and not open, the route still reads Ship's Records and counts every valid citing note (fail closed), because the next reset opens the archive and would promote them (X4). For archive entries it stays as S3 left it: after S4 no archive entry cites a live episode, because a tier 2 reset wipes the episodes it archives notes from (register R4), so it stays inert until S5.
  - **S3 R3 (a promotion landing between an erasure's checks): not S4's.** S4 promotes only at the offline reset under the pidfile, which excludes the running vessel and with it `/forget`. S5's in-vessel promoter owns it.
  - **S3 R4 (no lift), R5 (no listing by id), R8 (agent reach to the Captain-only CLI): unchanged in kind.** S4's notes add a source an agent could, if R8 holds, try to veto. That stays under S3's R8.
  - **S3 R6 (no bulk action): now reachable.** A refusal naming N notes needs N vetoes (register R12).
  - **S3 R11 (a shared attachment blob; BF-939, #1683): not S4's, and not S4's prerequisite.** S4's guarantee is about ids, and S4's archived citations name episodes the same reset wipes. BF-939 lands before S5 (register R16).
  - **S3 R13 (the N+1 citation read): scheduled to S5** (register R17). S4's own check reads Ship's Records once per request and adds no read per episode.
  - **S3 A2 (`entry_ids_citing` raises `ValueError` for an unreadable cell): unchanged.** S4 does not call it, and its archived cells are canonical (S15). S3's check runs before S4's at every entry point.
- **D17 (tiers and review).** M1, M2 and M3 are HIGH and each gets a cross-family review (`gpt-6.1-sol`). The 2026-10-18 slicing said one round for S4. That predates three things decided here: crew-authored text and the first real citations reach canon, the review stays opt-out (D12), and the erasure gains a refusal. Agent text written into canon without a chain-of-command review justifies the second model family.
- **D18 (the Captain).** Nothing meets a "Still requires the Captain" condition:
  - No operation against the live system: the build and every test run offline on `tmp_path`, with no vessel, no paid model call and no network.
  - No privacy control is weakened. C1 holds; citations are restricted to the agent's own offered episodes; the AD-754 check gains a refusal.
  - No public API or schema break: `SourceKind` gains a value in a TEXT column, and `/forget` gains a 409 for a new case.
  - No new external spending: at use, a stand-down spends at most one turn per crew agent on the Captain's configured providers, only when the Captain types `/stand-down`. That is the cost of the Captain sending each agent one 1:1 message.

  D12 (B) is recorded as overrulable.
- **D19 (not built).** S5: after-action reports, continuous promotion, the chain-of-command review (D12 B) and the in-vessel promotion race (S3 R3). S6: the `--full` snapshot, the nature description entry, `--clean-slate`. Also not built: fleet sharing, an HXI stand-down, a lift of a veto, a bulk veto, and configuration for the bounds.

**How each decision is tested:**

| Decision | Tests |
|---|---|
| D2 | S13 (console only; the API refuses and touches nothing), S13b, S11 |
| D3 | S12 (a real intent bus, `direct_message` from the Captain, never a non-crew agent, a refused turn writes nothing), S16 (A2: the real DM consumer answers inline, never promoted) |
| D4 | S9 |
| D5 | S3, S3b, S3c, S4, S4b, S4c, S6, S7, S7c, S7d |
| D6 | L1, L1b, L2, L3, L6; the one-parser rule by P2 `[body-not-in-format]` and S2 `[not-in-format]` |
| D7, D8, D9 | S1, S2b, S12, P1, P2, S7, S7b, S10b |
| D10 | P1, P2, S15 |
| D11 | S8, S8b, S8c, P3 |
| D12, D13 | C4, X2 |
| D14 | X1, X1c, X2, X3, X7 (the bound, through the route), X8, C1, C2, C3d |
| D15 | S15 |
| D16 | X4 |

Two decisions say "one X for two reads":

- **D6:** one parser for the stand-down and the promotion. P2 `[body-not-in-format]` changes the stored body between the stand-down's write and the promotion's read, and the promotion withholds the note.
- **D14:** one rule (`_exit_note_record` and `source_state`) for the erasure's read and the promotion. **C2** changes the state between the two reads: a veto lands after the citation read counted the note. The promotion refuses it and a second citation read no longer counts it.

**Disclosed effects.**
1. `SourceKind` gains `exit_note`. `user_version` stays 1; the column is TEXT.
2. `plan_promotion` lists `exit-notes/` documents. A valid note becomes a record attributed to the timeline that wrote it, and a malformed one is withheld, so the reset's withheld count includes it. The dry run and `probos archive pending` show notes.
3. `/stand-down` exists at the console. The HXI chat and the channel adapters answer that it is console-only.
4. A stand-down spends at most one model turn per crew agent (each turn is the agent's full 1:1 message chain). It takes at most 900 s plus cancellation.
5. Ship's Records gains `exit-notes/{timeline}/`.
6. `POST /api/security/forget` answers 409 `exit_notes_cite_erased_episodes` while a pending note cites a matched episode. With the archive enabled and not open, every valid citing note counts.
7. Each asked agent records the stand-down exchange in its own episodic memory, as it records any 1:1 message (register R11).
8. A2: `RecordsStore.list_entries` gains a keyword-only `strict` (default `False`, behaviour unchanged for every other caller).
9. A2: a `direct_message` whose params carry `bounded_turn: True` is answered on the single-pass path; no other DM changes.

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write each milestone's new test file first and run it on the milestone's base. It must fail at import (§6 names the error). §6's last column (the assertion each test fails at once the names exist but the behaviour is the base's) is the Architect's analysis, not a run you can make: do not try to reach it. If a test outside §7 fails, stop and report it; never delete or loosen a test.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** the format and the exit note's promotion | HIGH | 7.1 new `src/probos/knowledge/lessons.py`; 7.2 `src/probos/knowledge/archive_store.py`; 7.3 `src/probos/knowledge/archive_promotion.py`; 7.3a `src/probos/knowledge/records_store.py` (A2); 7.4 `tests/test_ad1341_s1_archive_store.py`; 7.5 new `tests/test_ad1341_s4_lessons.py` | `tests/test_ad1341_s4_lessons.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s2_inherited_label.py tests/test_ad1341_s3_veto_store.py tests/test_ad1341_s3_review_cli.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad524_ships_archive.py tests/test_records_store.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M2** the stand-down | HIGH | 7.6 new `src/probos/stand_down.py`; 7.7 new `src/probos/experience/commands/commands_stand_down.py`; 7.8 `src/probos/experience/shell.py`; 7.9 `src/probos/api.py`; 7.9a `src/probos/cognitive/cognitive_agent.py` (A2); 7.10 new `tests/test_ad1341_s4_stand_down.py` | `tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s3_erasure_cascade.py tests/test_shell.py tests/test_experience_commands.py tests/test_ad700a_diagnostic_slash_command.py tests/test_bf914_channel_allow_lists.py tests/test_callsign_routing.py tests/test_bf877_unapproved_design_is_refused.py tests/test_ad1053_actionable_notifications.py tests/test_ad1065_conversational_agentic.py tests/test_ad1165_turn_promotion.py tests/test_ad1070_capability_suppression.py tests/test_ad1070a_artifact_suppression.py tests/test_ad1180_agentic_disposition.py tests/test_bf698_thread_provenance.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M3** the AD-754 window | HIGH | 7.11 `src/probos/knowledge/erasure.py`; 7.12 `src/probos/routers/security.py`; 7.13 new `tests/test_ad1341_s4_exit_note_erasure.py` | `tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad1341_s3_review_cli.py tests/test_erasure_manager.py tests/test_ad1340_s1_erasure.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_bf905_erasure_live_scan.py tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2b_restore_route.py tests/test_ad1025b_path_anchoring.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M4** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

M1 adds `exit_note_citations` and tests it (C1 to C3c). Its consumer, the route, arrives in M3.

**Expected focused counts (measured by the orchestrator on the real base `20c1ec00`, replacing A1's figures, which predate S3's repair):** M1 480 passed, 1 skipped. M2 397 passed, 1 skipped. M3 403 passed. These predate A2. A2 adds M1 cases (two functions and parameter cases), M2's ten functions and six DM test files, and two M3 functions; the orchestrator re-measures on the repaired oracle. (A1's figures were M1 458, M2 388, M3 393.) No list changes: M1's list already holds `tests/test_ad1341_s1_promotion.py` (7.4a), and M2's and M3's hold `tests/test_ad1341_s3_erasure_cascade.py` (X1b imports its `_traced` and `_traces`). A5 adds C3g, C3h, C3i, P5 and P6 (M1: 25 cases), S2c, S4f, S8d and S13d (M2), a case each to C3e and S8c, and X8's fault parameter (nine cases for three); no list changes; the orchestrator re-measures.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `SourceKind.EXIT_NOTE` (`"exit_note"`) | `promote_entry` (stored as `source_kind` and `category`); `source_state`, `veto_source` (S3); `_pending_label` and `probos archive veto` (print `record.source_kind.value`); S1's closed-set pin (7.4) | a new kind; no column change |
| `source_kind_for` returns `EXIT_NOTE` for `exit-notes/` | `plan_promotion` and `exit_note_citations` (its two callers in `src`, Absence S4-AV3 as A4 corrected it) | notes enter the plan and the citation read |
| `plan_promotion`'s exit-note branch (`_exit_note_record`) | `promote_ship_records` (the reset), `review_promotion` (`pending`), `_veto_pending_source` (`veto`), `_show_promotion_plan` (dry run), `_promote_into_archive`'s no-instance-id refusal | notes promoted, reviewed, vetoable, listed; a bad one withheld |
| `exit_note_citations` | M3's route only (X6) | new |
| `probos.knowledge.lessons` | `archive_promotion.py`, `stand_down.py`; S1's import census of `archive_promotion.py` (`test_ad1341_s1_promotion.py:413-420`, 7.4a) | new; the census's pinned set gains it |
| `probos.stand_down` | `commands_stand_down.py` | new |
| `/stand-down` in `ProbOSShell.COMMANDS` and the handler map | `/help`; the console; `tests/*` that check single entries (none checks the whole set: Absence S4-AV4) | one more command |
| `_BLOCKED_COMMANDS` gains `/stand-down` | `_handle_slash_command` (HXI chat, `channels/base.py:367-370`) | console-only |
| `ErasureManager(..., exit_note_citations=None)` | `routers/security.py` (its one builder in `src`); tests build it positionally with three arguments or with S3's `archive_store=` | default None keeps every caller |
| `ExitNotesBlockErasure` | `request_erasure` (409); `_forget_all` counts it as a per-episode failure if raised inside the per-episode loop (it is raised first, at the top) | new |
| `POST /api/security/forget` 409 `exit_notes_cite_erased_episodes` | no HXI or CLI caller (S3-AV3); the route tests pass a `MagicMock` runtime whose `records_store` is not a `RecordsStore`, so they read no notes | new answer |
| Ship's Records `exit-notes/` | S1's promotion; the Oracle's records tier (keyword search); `list_entries` | new documents |
| `RecordsStore.list_entries(..., strict=False)` (A2, 7.3a) | default kept by every `RecordsStore` caller in `src`: `experience/commands/commands_gap.py:51`, `cognitive/dreaming.py:918`, `proactive.py:2735`, `cognitive/diagnostic_context.py:375`, `knowledge/archive_promotion.py:227` (`plan_promotion`; register R20), `knowledge/backlinks.py:263`, `knowledge/knowledge_linter.py:58`, `knowledge/notebook_quality.py:217`, `knowledge/semantic.py:708`, `routers/gaps.py:23`, `routers/records.py:50`, `:123`, `:134`, `:212`. `strict=True` (a file that cannot be read, and from A4 a directory that cannot be listed, raises): `exit_note_citations` and `run_stand_down`'s first read only | keyword-only; the default runs the same `rglob` call as before (C3f proves the strict walk's parity) |
| `direct_message` param `bounded_turn: True` (A2, 7.9a) | its one reader `CognitiveAgent._conversational_agentic_will_run`, and through it the dispatch (`cognitive_agent.py:4754`), the AD-1070 self-description (`:3214`) and the reply-tag suppressions (`:4206`, `:4254`). Sent only by `stand_down_vessel`. The channel adapters (`channels/base.py:452-457`), the console's 1:1 (`session.py:110-148`), System QA and every other sender never set it | a stand-down turn is single-pass and inline; no other DM changes |
| `LESSON_MAX_CHARS` (700) and the envelope bounds (A2) | `parse_lesson`; `exit_note_provenance_ok` (the stand-down before asking, and `_exit_note_record`); the prompt (S9); the Oracle tool's 1,200-character entry (`oracle_query_tool.py:71`, unchanged) | a whole note fits one tool entry (L6) |
| `TurnOutcome.DUPLICATE` (A2) | `cmd_stand_down` prints `outcome.value` | new outcome |
| `is_exit_note_text` refuses `---` (A4) | `exit_note_provenance_ok` (the stand-down's timeline refusal and `NO_IDENTITY`, and `_exit_note_record`); `_exit_note_record`'s episode-id check; `_offer` (A4) | a value Ship's Records would read back cut short (R25) is never asked for, offered or archived (P4, S7e, S10b) |
| `_NOT_LESSON_TEXT` (A4; was `_UNSTORABLE`) | `parse_lesson` only: the stand-down's reply and the promotion's stored body | a lesson holds no C0 or C1 control and no DEL but tab, line feed and carriage return (L3, L9) |
| `_SECTION` matches in ASCII only (A4) | `_HEADING_LINE`, `_ALONE_LINE`, `_LABEL_LINE`, so `_heading` and `parse_lesson` | a lookalike letter opens no section; nothing raises (L8, L10) |
| A turn's path on `failed` or `timed_out` (A4, A5) | `cmd_stand_down` prints any turn's path (`commands_stand_down.py:37-39`) and, from A5, counts the `failed` or `timed_out` turns that carry one apart from `written` (M2-2) | names a document a failed or cut-off write may have left, or whose presence could not be checked; nothing is removed |
| `_markdown_files_or_raise` (A5: an explicit `os.scandir` walk, files only) | `list_entries(strict=True)`, so `exit_note_citations` and `run_stand_down`'s first read (A5-AV1) | raises for every failure but a missing root (7.3a's table); lists what the default lists on a sound tree (C3f, C3g) |
| `exit_note_citations` raises for a ship-wide listed note `read_entry` cannot find (A5, O6) | `/forget` (500, nothing erased; the retry decides) | never "no citations" for a note listed a moment ago |
| `_present` (A5, O7) | `_write`'s check (unknown: `failed`, nothing written) and `_left_at` (unknown: the path named) | what `Path.exists` reads as "not there" (EBADF and the like) is unknown |
| `_stored_text` (A5) | `_title_for`, `plan_promotion`'s S1 record, `_exit_note_record` | a value `str()` cannot convert is archived as no value; every other value converts as before |

## 6. Tests

On each milestone's base, every test in its new file fails at import. The orchestrator ran each leg on the oracle (2026-10-26) and the errors are the first new name in each file's import order, not the module's own name:

- M1: `ImportError: cannot import name 'exit_note_citations' from 'probos.knowledge.archive_promotion'`: the file imports `archive_promotion` before `lessons`, so it cannot run against §7.1 alone and needs §7.3 (the name) before it imports.
- M2: `ImportError: cannot import name 'commands_stand_down' from 'probos.experience.commands'`, on M1's tree: the file imports `commands_stand_down` before `probos.stand_down`.
- M3: `ImportError: cannot import name 'ExitNotesBlockErasure'`.

The last column below is the Architect's analysis of the assertion each test fails at once the names exist but the behaviour is the base's. It is not a run: for M1 and M2 no run reaches it, because each milestone's names arrive together with its behaviour. The orchestrator's mutation census (§10) is the evidence that each test discriminates. "(new module)" means the whole behaviour is new, so the import is the failure on the base.

**M1, `tests/test_ad1341_s4_lessons.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| L1 | `test_a_rendered_lesson_parses_back_to_itself[one-line, multi-line]` | D6: the canonical form, headings in order, round trip | (new module) |
| L2 | `test_the_four_sections_are_read_in_each_heading_form[...7 forms]` | D6: heading forms; preamble dropped; `Cites:` line not kept; "Lesson learned, ..." stays text | (new module) |
| L3 | `test_a_reply_not_in_the_format_is_no_lesson[...14 cases]` | D6: missing, reordered, repeated, empty, over 700 in all, prose, not text; A2: a NUL, a lone surrogate; A4 (R2-F5): an ESC sequence, BEL, a C1 control, DEL, a vertical tab | (new module) |
| L4 | `test_a_declining_reply_is_recognised_and_nothing_else_is[...11]` | D4; A2 (M1-F8): `__NO NOTES__` and `_no notes_` decline, `no_notes` does not | (new module) |
| L5 | `test_citations_name_only_the_episodes_offered[...6]` | D9: only offered handles, once each, in order | (new module) |
| L5b | `test_a_lesson_cites_at_most_the_bounded_number_of_episodes` | D9: 12 | (new module) |
| L6 | `test_a_whole_note_at_every_bound_reaches_a_later_crew_through_the_oracle_tool` | D6 (A2, M1-F4): a note at every bound reaches a later crew through the real Oracle tool whole (four sections, nothing shortened), with room for the longest label and marker; one character more is refused | (new module) |
| L7 | `test_an_exit_note_has_one_path_per_timeline_and_agent_type` | D7: the slug rule; ValueError for no letter or digit | (new module) |
| P1 | `test_an_exit_note_is_promoted_with_its_own_provenance` | D9, D10: the row's timeline (the note's, not the reset's), kind, title, content, author type, callsign, DID, citations, classification | `promoted.created == (path,)` (base: an `exit-notes/` path is no source) |
| P2 | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing[...23 cases]` | D6, D9, D10: each break withheld; the plan never raises; the citation read counts none. A2: a `True` or `1.0` version (M1-F7); a line break, NUL or over-long value in the provenance and a DID SQLite cannot store (M1-F2, M1-F6, M2-7); a preamble or a standalone `Cites:` line in the stored body (M1-F5). A4: an over-long or line-broken episode id (R2-F4's missing case), a lookalike heading (R2-F2: withheld, never raised), a control character in the body (R2-F5) | `plan.records == ()` (A2's and A4's cases: the base selects them, or raises) |
| P3 | `test_an_exit_note_is_archived_once_whichever_reset_promotes_it` | D11 | `first.created == (path,)` |
| C1 | `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it[new, vetoed, erased, present, uncited, no-archive]` | D14, D16: one rule; fail closed with no archive | `cited == expected` |
| C2 | `test_a_veto_between_the_citation_read_and_the_promotion_decides_both` | D14, the case that changes the state between the two reads | `before == {...}` |
| C3 | `test_the_citation_read_raises_when_ship_s_records_cannot_be_listed` | D14: a failed read is never "no citations" | `pytest.raises(OSError)` |
| C3b | `test_ship_s_records_without_exit_notes_cite_nothing` | the empty case, and the missing `exit-notes/` directory | (new function) |
| C3c | `test_a_document_the_promotion_skips_is_never_read_as_a_citing_note[not-a-mapping, not-utf-8]` | A1, D14's one rule: frontmatter that is not a mapping; A2: bytes that are not UTF-8 (a property of the file). The promotion skips it, and so does the strict citation read | (new function; on A0's code: `AttributeError` from `read_entry`; `[not-utf-8]` is a control) |
| C4 | `test_the_captain_s_review_lists_an_exit_note_as_a_source_to_be_promoted` | D12, D13: S3's review sees the note | `[...] == [(path, PromotionOutcome.CREATED)]` |
| L1b | `test_every_lesson_the_parser_accepts_is_written_and_read_back_unchanged[...11 cases]` | A2 (M1-F3): the format is closed under rendering; four ambiguous inline or stripped bodies are refused | `assert lesson is None` (the four refusal cases) |
| C3d | `test_a_note_the_listing_cannot_read_now_is_never_read_as_no_citations[injected, native]` | A2 (M1-F1): a valid note the OS refuses to read now; the real listing meets the failure inside its loop; the citation read raises; the default listing still skips it; once readable it counts. `[native]`: a share-nothing handle on Windows, mode 000 on POSIX (skips only where the account reads it anyway) | `pytest.raises(OSError)` (did not raise) |
| L8 | `test_a_section_name_spelled_with_a_lookalike_letter_opens_no_section` | A4 (R2-F2): the four letters Unicode IGNORECASE folds onto ASCII (premise: Python's documented set), in every section name and four heading forms: refused, never raised | the parser raises `KeyError` (base) |
| L9 | `test_a_lesson_carries_no_control_character_but_tab_line_feed_and_carriage_return` | A4 (R2-F5): every C0 and C1 control and DEL refused anywhere in a reply; tab kept; line feed and carriage return end lines | `assert lesson is None, hex(code)` at `0x1`, `0x1b` (base: accepted) |
| L10 | `test_a_note_the_rule_refuses_is_withheld_and_the_real_reset_still_runs` | A4 (R2-F2): a stored lookalike heading through the real `probos reset`: exit 0, the note not archived | `_reset(...) == 0` (base: 1) |
| P4 | `test_every_provenance_value_the_rule_admits_comes_back_whole_from_ship_s_records[callsign, agent_type, did, cited]` | A4 (R2-F3): YAML's quoting cases and, for the callsign, every code point to U+017F: refused and withheld, or admitted, stored, read back whole and archived | `(record,) = plan.records` for a value holding `---` (base: admitted, then withheld) |
| C3e | `test_a_note_directory_the_listing_cannot_list_now_is_never_read_as_no_citations[injected-root, injected-timeline, injected-entry-type, native-root, native-timeline]` | A4 (R2-F1, M3-1): `exit-notes/` or a timeline directory the OS refuses to list; A5 (R3-M1-1): `[injected-entry-type]`, the OS cannot report the timeline directory's type (the round-3 P1); the strict listing and the citation read raise; the default listing never raises (and, natively, passes over it); listable again, the note counts | `pytest.raises(OSError)` (did not raise; on `bbc64351` only `[injected-entry-type]`) |
| C3f | `test_the_strict_listing_lists_exactly_what_the_default_listing_lists[all, exit-notes, absent]` | A4: the strict walk's parity with `rglob("*.md")`: nested directories, a `*.md` directory, another suffix, the suffix's case as the platform matches it, `_archived/`, a missing directory | (passes on the base, where `strict` changes no traversal: the control; A5: the walk returns files only and `list_entries` lists the same; kills RS-10) |
| K1 | `tests/test_ad1341_s1_archive_store.py::test_source_kinds_are_closed_and_none_is_an_episode` (updated) | the closed set gains `exit_note`; none is an episode | the set equality (base: no `exit_note`) |
| K2 | `tests/test_ad1341_s1_promotion.py::test_the_service_imports_only_the_knowledge_layer` (updated, A1, 7.4a) | the promotion service still imports only the knowledge layer, now with `probos.knowledge.lessons` | the set equality (base: no `lessons` import, until 7.3 pair 2) |
| C3g | `test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing[absent, io, not-a-directory, permission]` | A5 (R3-M1-1; 7.3a's O1 to O4): a trace-and-fault matrix. A clean walk over a real tree records every operation (each `os.scandir`, each listing step including the last, each `is_dir`); an entry offers only `name` and `is_dir(follow_symlinks=False)`, and `os.stat`, `os.lstat`, `os.listdir`, `os.walk` trip, so an operation without a row fails. Then each recorded operation fails once with the kind: the walk raises it, except a missing root (`[absent]`, `[not-a-directory]` at the root's open), which lists nothing. Every cell asserts its fault fired where aimed | the clean run's `follow_symlinks is False` (base: `os.walk` calls `is_dir()`, then `os.path.islink`) |
| C3h | `test_a_listed_note_the_strict_read_cannot_read_is_never_read_as_no_note[permission, io, absent, not-a-directory × stat-ok, stat-ebadf]` | A5 (O5): a listed note whose read fails with any error raises from the strict listing and the citation read; the default still skips it; readable again, it counts. `[*-stat-ebadf]`: A2's `is_file()` answered "not there" | `pytest.raises(OSError)` (did not raise) in the four `[*-stat-ebadf]` cases; `[*-stat-ok]` pass on the base |
| C3i | `test_a_listed_note_the_citation_read_cannot_find_again_is_never_read_as_no_citations[ebadf, enoent, eacces]` | A5 (O6): the strict listing returned and read the note; `read_entry`'s `Path.exists` cannot find it now: the citation read raises; readable again, it counts. `[eacces]`: `exists` raises itself (the control) | `pytest.raises(OSError)` (base: `{}`) for `[ebadf]`, `[enoent]` |
| P5 | `test_a_stored_value_that_cannot_be_shown_as_text_never_stops_the_promotion[...9 cases]` | A5 (R3-M1-2): a YAML integer (`0x` and 4,000 digits) in each value the promotion converts: the exit note's status, created, updated; a notebook finding's author, status, department, created, updated, topic (S1's sources). The plan selects the document; the value is archived as no value; the title falls back to the file name | `plan_promotion` raises `ValueError` (all nine) |
| P6 | `test_a_note_holding_a_value_that_cannot_be_shown_as_text_is_archived_by_the_real_reset` | A5 (R3-M1-2): the reviewer's case through the real `probos reset`: exit 0, the note archived | `_reset(...) == 0` (base: 1) |

**M2, `tests/test_ad1341_s4_stand_down.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| S1 | `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance` | D3, D7 to D9: one turn each; frontmatter, envelope, body; no preamble, `Cites:` line or episode text kept | (new module) |
| S2 | `test_writing_is_optional_and_a_turn_that_leaves_no_lesson_writes_nothing[declined, not-in-format, no-reply, failed]` | D4, D6 | (new module) |
| S3 | `test_a_turn_that_runs_past_its_bound_is_cancelled_and_writes_nothing` | D5: the turn bound; cancellation | (new module) |
| S4 | `test_the_window_closes_on_time_and_writes_nothing_late_or_unreached` | D5: a reply after the window and an agent not reached write nothing (a controlled clock) | (new module) |
| S4b | `test_the_window_bounds_a_turn_its_own_bound_would_allow` | D5: real time, window below the turn bound | (new module) |
| S6 | `test_no_more_than_the_bounded_number_of_turns_run_at_once` | D5: concurrency 2 | (new module) |
| S6b | `test_the_stand_down_writes_one_note_at_a_time` | A1, 7.6's write lock: two turns at once, never two Ship's Records writes | (new module) |
| S7 | `test_a_note_cites_only_episodes_the_agent_was_shown` | D4, D9: 12 shown, 160 characters, other handles dropped | (new module) |
| S7b | `test_a_failed_episode_read_offers_none_and_the_note_cites_none` | D5: log and degrade | (new module) |
| S8 | `test_a_second_stand_down_asks_only_the_agents_without_a_note` | D11 | (new module) |
| S9 | `test_the_prompt_says_writing_is_optional_and_what_the_note_is_for` | D4 | (new module) |
| S10 | `test_an_agent_without_an_identity_is_not_asked` | D9 | (new module) |
| S11 | `test_the_stand_down_refuses_when_nothing_could_be_kept_or_attributed[archive-disabled, no-records, no-instance-id, unknown-instance-id]` | D2; each case's own refusal text (`match=`, A1) | (new module) |
| S12 | `test_the_vessel_stand_down_sends_each_crew_agent_the_captains_message_through_the_intent_bus` | D3: real `IntentBus`; non-crew never asked; a refused turn writes nothing; DID from the identity service | (new module) |
| S13 | `test_only_the_console_runs_a_stand_down` | D2: the shell dispatches it; the API refuses it and touches nothing | (new module) |
| S13b | `test_the_console_command_reports_each_turn_and_the_next_steps` | D13 | (new module) |
| S14 | `test_the_stand_down_never_writes_the_ship_s_archive` | D7 D: no archive import; no archive write call | (new module) |
| S15 | `test_a_stand_down_note_reaches_a_later_crew_as_inherited_and_its_citation_reaches_the_erasure_check` | **the real seam:** the vessel stand-down (real bus, the model a stub) → the real `probos reset` promotes it → a later crew's real Oracle returns it with "[Inherited from the crew of generation 1: not your own memory]" first → S3's real check refuses an AD-754 erasure of the cited episode | (new module) |
| S2b | `test_a_write_that_fails_after_publishing_leaves_no_hidden_note[published, replaced, not-published]` | A2 (M2-4), A4: the stand-down removes nothing. A note a failed write published is reported failed with its path and is promotable; another writer's document at the path stays as it was; a write that failed before publishing leaves nothing and the billet is asked again | `(FAILED, path)` (base: `(FAILED, "")`, the note removed) / the author `Bones` (base: removed) |
| S3b | `test_a_reply_that_returns_after_the_turn_s_deadline_writes_nothing` | A2 (M2-5): a cancellation-suppressing ask returning after the turn's deadline, inside the window | `[TurnOutcome.TIMED_OUT]` (base: WRITTEN) |
| S3c | `test_the_recall_and_the_ask_spend_one_turn[slow-recall, recall-runs-out]` | A2 (M2-5): one deadline per turn | `[TurnOutcome.TIMED_OUT]` (base: WRITTEN) |
| S4c | `test_the_window_bounds_the_records_reads_and_writes_too[first-read, write]` | A2 (M2-2): a hanging first read refuses with nobody asked; a hanging write is cut off by the window; A4: on the injected clock, the turn queued behind it for the write lock never begins a write. It proves the guard's logic, not the real timer (S4d is the real clock) | `pytest.raises(StandDownRefused)` / the outcomes |
| S7c | `test_the_captain_s_message_stays_inside_the_inline_params_bound_in_any_script[ascii, cjk, astral]` | A2 (M2-8): 12 episodes and a 32-character CJK callsign; params as JSON at most 4,096 bytes; 12 shown | `len(json.dumps(intent.params)) <= 4096` (`[ascii]` a control) |
| S7d | `test_one_member_s_fault_never_ends_the_other_turns_or_leaves_one_running[timestamps, unreadable-episode, self-cancelled]` | A2 (M2-6): inf and NaN shown undated; one member's unreadable episode fails that member only; a turn cancelled from inside cancels and drains the rest; no task outlives the call | the call raises `OverflowError` / `RuntimeError`; `stopped.is_set()` |
| S8b | `test_one_billet_gets_one_turn_and_no_note_is_ever_replaced[same-type, same-member, written-meanwhile]` | A2 (M2-3) | the outcomes (base: two WRITTEN; asked twice; revision 2) |
| S8c | `test_a_stand_down_that_cannot_read_a_written_note_asks_nobody[file, directory, entry-type]` | A2 (M1-F1 asked of the stand-down): a skip would replace the note; A4 (M3-1): a billet directory the OS refuses to list; A5 (O4): a note whose type the OS cannot report | `pytest.raises(StandDownRefused)` (did not raise; on `bbc64351` only `[entry-type]`) |
| S10b | `test_an_identity_that_cannot_stand_in_the_note_is_not_asked[multiline-callsign, long-callsign, nul-agent-type, surrogate-did, delimiter-callsign]` | A2 (M2-7); A4 (R2-F3): a callsign holding `---` | `[TurnOutcome.NO_IDENTITY]` (base: WRITTEN) |
| S4d | `test_on_the_real_clock_no_write_begins_after_the_window_and_every_note_left_is_reported[the-check-outlasts-the-window, a-write-returns-late, cut-off-after-publishing]` | A4 (round 2 M2-2, M2-4, M2-7): the real clock with 200 ms of margin over the 15.6 ms tick; the existence check (A5: `Path.lstat`, the seam slowed) is charged to the window; a late synchronous return is `written` with its note; a write cut off after publishing is `timed_out` with the path it left | `writes == []` (base: a write began after the window) / `(TIMED_OUT, path)` (base: `(TIMED_OUT, "")`, the note removed) |
| S4e | `test_a_cancelled_stand_down_keeps_every_note_it_published_and_leaves_nothing_running` | A4 (round 2 M2-3): the cancellation propagates; no task outlives it; the published note stays whole and reviewable (register R27) | (passes on the base: the control pinning A4's decision) |
| S7e | `test_every_episode_offered_can_be_cited_by_a_note_the_promotion_archives[long, nul, surrogate, line-break, delimiter]` | A4 (R2-F4, M2-5): an episode whose id the rule refuses is never offered or shown; every offered id is cited, stored and archived | `[...source_episode_ids...] == [("ep-000", "ep-001")]` (base: `[]`, the note withheld) |
| S11b | `test_a_bound_that_is_not_positive_is_refused_before_anything_is_read[turn, window, concurrency]` | A4 (M2's record): `ValueError` before the first read, nobody asked | (passes on the base; D-41 is its evidence) |
| S13c | `test_the_console_command_takes_no_arguments` | A4 (M2's record): the usage line; the runtime untouched | (passes on the base; C-2 is its evidence) |
| S16 | `test_a_stand_down_turn_is_answered_inline_by_the_real_dm_consumer_and_never_promoted` | A2 (M2-1), **the real seam:** real `CognitiveAgent` consumers with the shipped `dm_agentic` settings; the turns take the single-pass path, the loop's model is never called, no work item, no promoted task; the control's ordinary 1:1 still runs the loop | `intent.params[BOUNDED_TURN_PARAM]` (KeyError) |
| S2c | `test_a_failed_write_whose_note_cannot_be_checked_still_names_its_path` | A5 (round 3 M2-4): a write publishes and then fails, and `Path.lstat` of the billet raises: unknown counts as there, so the report names the path | `assert checks` (base: checks with `Path.exists`); its evidence is D-43 and D-46 |
| S4f | `test_a_first_read_that_returns_after_the_window_asks_nobody_and_starts_no_turn` | A5 (round 3 M2-3): a first read that never yields returns after the window (injected clock): `StandDownRefused` before any turn task is created; nobody asked | `pytest.raises(StandDownRefused)` (base: a report, every turn `not_reached`) |
| S8d | `test_a_billet_whose_note_cannot_be_checked_is_never_written_over` | A5 (O7): a note written meanwhile, then `Path.stat` and `Path.lstat` of the billet fail with EBADF (which `Path.exists` reads as "not there"): `failed` with no path, no write, the note unrevised | `[(FAILED, "")]` (base: `written`, revision 2) |
| S13d | `test_the_console_counts_completed_writes_and_names_a_note_a_failed_write_may_have_left` | A5 (round 3 M2-2): after a write that published and then failed, the console prints the turn with its path, `0 exit note(s) written`, and that one write did not complete and may have left a document; the next reset would archive it | the "did not complete" line (base: absent) |

**M3, `tests/test_ad1341_s4_exit_note_erasure.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| X1 | `test_an_erasure_a_pending_exit_note_cites_erases_nothing[episode, agent, resource]` | D14: a real `EpisodicMemory`; nothing erased; the path named | `pytest.raises(ExitNotesBlockErasure)` |
| X1b | `test_a_refused_erasure_for_a_note_keeps_the_cited_episodes_attachment_and_audit_row[episode, agent, resource]` | A1, S3's finding M3-F1 asked of this check: S3's real `FilesystemAttachmentStore` and `AuditLog` (`_traced`); the refusal precedes the unlink and the audit marking | `pytest.raises(ExitNotesBlockErasure)` |
| X2 | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes[episode, agent]` | **the real seam:** real stand-down → real `/forget` 409 with the path, nothing erased → the Captain's real `probos archive veto` → retry 200 → the real `probos reset` archives no note; A2 (M3-F5): the refusal is logged once, as a count, with no path, id or text | `refused.status_code == 409` (base: 200) |
| X3 | `test_a_note_the_next_reset_would_not_archive_with_this_citation_blocks_nothing[vetoed, erased, present, uncited, another-episode]` | D14 | (passes once the keyword exists: the control) |
| X4 | `test_the_check_fails_closed_while_the_archive_is_enabled_but_not_open[enabled-not-open, disabled]` | D16: S3's R2 for notes | `answer.status_code == 409` |
| X5 | `test_the_forget_route_reads_notes_only_from_a_real_records_store` | the route tests' `MagicMock` runtime is no records store; its premise (A1) shows a real store's read counts the note | (passes on the base: the control; kills R-3) |
| X6 | `test_only_the_forget_route_reads_exit_note_citations_and_only_the_manager_refuses_on_them` | census | `_importers("exit_note_citations") == {"routers/security.py"}` |
| X7 | `test_a_note_written_after_the_request_read_its_citations_does_not_stop_it` | D14's disclosed bound, through the real route (A2, M3-F3): one read; the late note lands after it and before the manager; a second read counts it | (passes once the keyword exists: the control; kills R-8) |
| X1c | `test_s3_s_archive_refusal_comes_before_this_slice_s_when_both_cite_the_episode[episode, agent, resource]` | A2 (M3-F4): an archived note and a pending note both cite the target; S3's refusal comes first | (a control on the base's order; kills E-7, E-8) |
| X8 | `test_an_exit_note_the_route_cannot_read_now_refuses_the_erasure[read, listing, entry-type × episode, agent, resource]` | A2 (M3-F1, A3), A5 (round 3 R3-M1-1, M3's coverage): during the request the OS refuses to read the note, to list its timeline directory, or to report that directory's type; through a transport that answers as a served app does (`raise_app_exceptions=False`); 500 with the body `Internal Server Error`, the one exception the app raised a `PermissionError`, nothing erased; the fault lifted, 409 with its path and no further exception | `failed.status_code == 500` (base: 200; on `bbc64351` only `[entry-type-*]`: 200, erased) |

**Controls (A1).** C3b, X3, X5 and X7 pass on the base's behaviour by design (C3b: nothing to read; X3 and X7: once the keyword exists; X5: on the M3 base). None of them is evidence of a refusal on its own. X3 kills P-10's mutant (a note the read wrongly counts would refuse). X5 kills R-3, and its premise asserts that a real store's read counts the note. X7's premise asserts that a second read counts the late note, so its pass comes from the one-read bound and not from an invalid note. Every refusal asserts its own type or text, which the base's behaviour cannot produce: `ExitNotesBlockErasure` with `.paths` (X1, X1b), `exit_notes_cite_erased_episodes` and `exit_note_paths` (X2, X4), each case's `StandDownRefused` text (S11), `only available in the CLI terminal` (S13), and `Stand-down refused` (S13b).

## 7. The contract

### 7.1 New file: `src/probos/knowledge/lessons.py` (M1)

```python
"""AD-1341 S4 (#1569): the lessons format, and the exit note that carries a lesson across a reset.

A lesson has four sections, in this order, after the naval lessons-learned systems the Captain named (#1569 comment 1):

- Observation: what happened, citing the source episodes;
- Discussion: why it happened and why it mattered;
- Lesson: the general learning;
- Recommendation: what to do differently.

``parse_lesson`` is the one reader. The stand-down (``probos.stand_down``) reads an agent's reply with it, and the
reset's promotion (``probos.knowledge.archive_promotion``) reads the stored note with it, so the archive accepts only
what a stand-down could have written. ``LessonLearned.render`` is the one writer, and a rendered lesson parses back to
itself.

An exit note is the lesson an agent leaves for its successor before a reset: a Ship's Records document at
``exit_note_path(timeline, agent_type)`` whose body is ``exit_note_header`` followed by the rendered lesson, and whose
``exit_note`` frontmatter holds its provenance. It names the agent's own episodes by id; no episode text is copied
into it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

#: The four sections of a lesson, in order.
LESSON_SECTIONS: Final = ("Observation", "Discussion", "Lesson", "Recommendation")

#: The longest a lesson may be: its four sections together, in characters (AD-1341 S4 A2). With the envelope bounds
#: below, a whole archived exit note (the Oracle tool's provenance marker and S2's inheritance label, the
#: ``[exit_note]`` title, the origin line and the four sections) fits one Oracle tool entry (1,200 characters,
#: ``oracle_query_tool._MAX_ENTRY_CHARS``), so a later crew reads the Lesson and the Recommendation, not only the
#: Observation.
LESSON_MAX_CHARS: Final = 700

#: The longest value of each exit-note envelope field (A2). The timeline, callsign and agent type stand in the origin
#: line, and the callsign in the Oracle entry's title, so these bounds are part of the Oracle-entry budget above.
EXIT_NOTE_TIMELINE_MAX_CHARS: Final = 64
EXIT_NOTE_CALLSIGN_MAX_CHARS: Final = 32
EXIT_NOTE_AGENT_TYPE_MAX_CHARS: Final = 48
EXIT_NOTE_DID_MAX_CHARS: Final = 256
EXIT_NOTE_EPISODE_ID_MAX_CHARS: Final = 128

#: The most episodes a lesson cites, and the most a stand-down shows an agent.
LESSON_MAX_CITATIONS: Final = 12

#: The reply that declines. Writing exit notes is optional.
DECLINE_REPLY: Final = "NO NOTES"

#: Where exit notes live in Ship's Records, the frontmatter key that holds their provenance, its version, and the
#: status a stand-down writes them at.
EXIT_NOTES_DIR: Final = "exit-notes"
EXIT_NOTE_KEY: Final = "exit_note"
EXIT_NOTE_VERSION: Final = 1
EXIT_NOTE_STATUS: Final = "submitted"

_NAMES = {name.lower(): name for name in LESSON_SECTIONS}
_SECTION_NAMES = "observation|discussion|lesson|recommendation"
# A4 (R2-F2): the names match in ASCII only. Under re.IGNORECASE alone, U+0130, U+0131 and U+017F match as ASCII
# letters ("Ob\u017fervation"), and _NAMES holds only the ASCII names, so such a heading raised KeyError.
_SECTION = f"((?a:{_SECTION_NAMES}))"
_EMPHASIS = r"(?:\*\*|__)?"
# "## Observation" or "### Observation:": a markdown heading alone on its line.
_HEADING_LINE = re.compile(rf"^\s{{0,3}}#{{1,6}}\s*{_SECTION}\s*:?\s*#*\s*$", re.IGNORECASE)
# "**Observation**" or "Observation": the name alone on its line, bold or plain.
_ALONE_LINE = re.compile(rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*$", re.IGNORECASE)
# "Observation: text", "**Observation:** text", "**Observation**: text". A label needs its colon, so a sentence that
# begins with a section's name ("Lesson learned, ...") stays text.
_LABEL_LINE = re.compile(
    rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*:\s*{_EMPHASIS}\s*(.*)$", re.IGNORECASE,
)
_CITES_LINE = re.compile(rf"^\s{{0,3}}{_EMPHASIS}\s*cites?\s*{_EMPHASIS}\s*:\s*(.*)$", re.IGNORECASE)
_HANDLE = re.compile(r"\be(\d{1,2})\b", re.IGNORECASE)
_DECLINED = re.compile(r"^[\W_]*no notes[\W_]*$", re.IGNORECASE)  # A2: _ is emphasis too (__NO NOTES__, _NO NOTES_)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")
# A2: what SQLite cannot store whole: a NUL ends its length() and keyword search, and a lone surrogate is no UTF-8.
# A4 (R2-F5): and what a console acts on: the Captain reads exit notes at a terminal, where an ESC sequence redraws it.
# So a lesson holds no C0 or C1 control and no DEL, except tab, line feed and carriage return (which end lines).
_NOT_LESSON_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
# A2: what cannot stand in one line of an exit note: every control character, the line and paragraph separators (each
# ends a line for str.splitlines), and lone surrogates.
_NOT_ONE_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")
# A4 (R2-F3): Ship's Records splits a document's frontmatter at the first two "---" it finds, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one would come back cut short.
_FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True)
class LessonLearned:
    """One lesson in the four-section format. ``parse_lesson`` builds it and enforces the format.

    Not ``Lesson``: ``probos.cognitive.self_improvement`` already exports a ``Lesson`` (``evolution_store.py``), a
    self-improvement outcome with other fields (AD-1341 S4 A1).
    """

    observation: str
    discussion: str
    lesson: str
    recommendation: str

    def render(self) -> str:
        """The lesson as markdown: each section under its ``##`` heading, in order. ``parse_lesson`` reads it back."""
        bodies = (self.observation, self.discussion, self.lesson, self.recommendation)
        return "\n\n".join(f"## {name}\n\n{body}" for name, body in zip(LESSON_SECTIONS, bodies, strict=True))


def _heading(line: str) -> tuple[str, str] | None:
    """The section a line opens and any text after its label, or None when the line opens no section."""
    for pattern in (_HEADING_LINE, _ALONE_LINE):
        match = pattern.match(line)
        if match is not None:
            return _NAMES[match.group(1).lower()], ""
    match = _LABEL_LINE.match(line)
    if match is not None:
        return _NAMES[match.group(1).lower()], match.group(2).strip()
    return None


def parse_lesson(text: object) -> LessonLearned | None:
    """The lesson in ``text``, or None when ``text`` is not in the format (D6).

    The four sections must each appear once, in order, each non-empty, together at most ``LESSON_MAX_CHARS``
    characters. A heading is a markdown heading (``## Observation``), the name alone on its line (``**Observation**``,
    ``Observation``) or a label with a colon (``Observation: text``). Text before the first heading is not part of the
    lesson and is dropped. A ``Cites:`` line belongs to ``parse_citations`` and is never part of a section.

    A2: the format is closed under ``LessonLearned.render``. A section whose text would read as a heading or a
    ``Cites:`` line once rendered on its own line (``Observation: Discussion: ...``) is refused, so every accepted
    lesson is written, stored and read back unchanged. Text SQLite cannot store whole (a NUL, a lone surrogate) is
    refused, and A4 (R2-F5) refuses every other C0 and C1 control and DEL but tab, line feed and carriage return.
    """
    if type(text) is not str or _NOT_LESSON_TEXT.search(text) is not None:
        return None
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        heading = _heading(line)
        if heading is not None:
            name, rest = heading
            sections.append((name, [rest] if rest else []))
        elif _CITES_LINE.match(line):
            continue
        elif sections:
            sections[-1][1].append(line)
    if tuple(name for name, _lines in sections) != LESSON_SECTIONS:
        return None
    bodies = tuple("\n".join(lines).strip() for _name, lines in sections)
    if any(not body for body in bodies) or sum(len(body) for body in bodies) > LESSON_MAX_CHARS:
        return None
    if any(_heading(line) is not None or _CITES_LINE.match(line) for body in bodies for line in body.splitlines()):
        return None  # A2: rendered on its own line, this text would open a section or be read as citations
    return LessonLearned(*bodies)


def is_declined(text: object) -> bool:
    """Whether a reply declines: empty, or ``DECLINE_REPLY`` with nothing around it but punctuation or emphasis."""
    if type(text) is not str:
        return False
    stripped = text.strip()
    return not stripped or _DECLINED.match(stripped) is not None


def parse_citations(text: object, offered: Mapping[str, str]) -> tuple[str, ...]:
    """The episode ids a reply's ``Cites:`` lines name, in order of first mention (D9).

    Only handles in ``offered`` count (``e1`` -> the id of an episode the agent was shown); any other handle is
    dropped. Each id once, at most ``LESSON_MAX_CITATIONS``.
    """
    if type(text) is not str:
        return ()
    cited: list[str] = []
    for line in text.splitlines():
        match = _CITES_LINE.match(line)
        if match is None:
            continue
        for number in _HANDLE.findall(match.group(1)):
            episode_id = offered.get(f"e{int(number)}")
            if episode_id is not None and episode_id not in cited and len(cited) < LESSON_MAX_CITATIONS:
                cited.append(episode_id)
    return tuple(cited)


def _slug(value: object, name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"AD-1341 S4: {name} must be a string")
    slug = _NOT_SLUG.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"AD-1341 S4: {name} has no letter or digit to name a records path with")
    return slug


def exit_notes_directory(timeline_id: str) -> str:
    """The Ship's Records directory that holds one timeline's exit notes."""
    return f"{EXIT_NOTES_DIR}/{_slug(timeline_id, 'timeline_id')}"


def exit_note_path(timeline_id: str, agent_type: str) -> str:
    """The one Ship's Records path of an agent's exit note in a timeline: ``exit-notes/{timeline}/{agent_type}.md``.

    Keyed by agent type, not callsign: a callsign can repeat across generations (AD-1341 S2, RS2-3).
    """
    return f"{exit_notes_directory(timeline_id)}/{_slug(agent_type, 'agent_type')}.md"


def exit_note_header(callsign: str, agent_type: str, timeline_id: str) -> str:
    """An exit note's fixed first line: who left it, for whom, and that it is a record, not a memory (D15)."""
    return (
        f"Exit notes left by {callsign} ({agent_type}) of the crew of timeline {timeline_id} for their successor. "
        "A record, not a memory."
    )


def exit_note_body(callsign: str, agent_type: str, timeline_id: str, lesson: LessonLearned) -> str:
    """An exit note's body: its origin line, then the rendered lesson. Nothing else is written into a note."""
    return f"{exit_note_header(callsign, agent_type, timeline_id)}\n\n{lesson.render()}"


def is_exit_note_text(value: object, max_chars: int) -> bool:
    """A2: whether ``value`` can stand in an exit note's envelope and origin line.

    A string of at most ``max_chars`` characters that is not blank and is one line: no control character, no line or
    paragraph separator, no lone surrogate. SQLite stores the value as UTF-8 and a NUL would end its ``length()`` and
    keyword search; a line break in a callsign would put another heading into the origin line. A4 (R2-F3): and no
    ``---``, which Ship's Records would take for the end of the frontmatter, so the value would come back cut short.
    """
    return (
        type(value) is str and bool(value.strip()) and len(value) <= max_chars and _NOT_ONE_LINE.search(value) is None
        and _FRONTMATTER_DELIMITER not in value  # A4 (R2-F3): Ship's Records cuts a frontmatter value at "---"
    )


def exit_note_provenance_ok(timeline_id: object, callsign: object, agent_type: object, author_did: object) -> bool:
    """A2: whether an exit note's provenance can be written into its envelope and origin line, each within its bound.

    The one check for the stand-down, before it asks an agent, and for the promotion's rule.
    """
    return all(
        is_exit_note_text(value, max_chars)
        for value, max_chars in (
            (timeline_id, EXIT_NOTE_TIMELINE_MAX_CHARS),
            (callsign, EXIT_NOTE_CALLSIGN_MAX_CHARS),
            (agent_type, EXIT_NOTE_AGENT_TYPE_MAX_CHARS),
            (author_did, EXIT_NOTE_DID_MAX_CHARS),
        )
    )


def exit_note_lesson(callsign: str, agent_type: str, timeline_id: str, content: object) -> LessonLearned | None:
    """A2: the lesson of a canonical exit-note body, or None.

    Canonical: ``content`` is exactly ``exit_note_body`` of these fields and the lesson it holds, so the text the
    Captain reviews in Ship's Records is the text the archive receives, and nothing the parser would drop (a preamble,
    a ``Cites:`` line) is ever archived. The stand-down checks its own body with it before writing; the promotion
    withholds a note it refuses.
    """
    lesson = parse_lesson(content)
    if lesson is None or content != exit_note_body(callsign, agent_type, timeline_id, lesson):
        return None
    return lesson
```

### 7.2 `src/probos/knowledge/archive_store.py` (M1)

SEARCH:
```python
    CONVERGENCE_REPORT = "convergence_report"
    PUBLISHED_REPORT = "published_report"
    CAPTAINS_LOG = "captains_log"
    NOTEBOOK_FINDING = "notebook_finding"
```
REPLACE:
```python
    CONVERGENCE_REPORT = "convergence_report"
    PUBLISHED_REPORT = "published_report"
    CAPTAINS_LOG = "captains_log"
    NOTEBOOK_FINDING = "notebook_finding"
    EXIT_NOTE = "exit_note"  # AD-1341 S4: a lesson a crew agent leaves for its successor; it cites episodes, never is one
```

### 7.3 `src/probos/knowledge/archive_promotion.py` (M1)

Pair 1 (the module docstring):

SEARCH:
```python
- Ship's Records carry no source-episode ids, so a records-sourced entry carries none (the lessons slice
  adds them).
```
REPLACE:
```python
- Ship's Records carry no source-episode ids, so a records-sourced entry carries none. AD-1341 S4: an exit note
  (``exit-notes/``) is the exception. A stand-down writes it with its author's DID, callsign and agent type and the ids
  of the episodes it cites, and ``_exit_note_record`` turns it into an entry attributed to the timeline that wrote it.
  ``exit_note_citations`` is the AD-754 erasure's read of the citations the next promotion would archive.
```

Pair 2 (imports):

SEARCH:
```python
from probos.knowledge.records_store import RecordsStore
```
REPLACE:
```python
from probos.knowledge.lessons import (
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_VERSION,
    EXIT_NOTES_DIR,
    LESSON_MAX_CITATIONS,
    exit_note_lesson,
    exit_note_path,
    exit_note_provenance_ok,
    is_exit_note_text,
)
from probos.knowledge.records_store import RecordsStore
```

Pair 3 (the criterion's docstring):

SEARCH:
```python
    - ``notebooks/`` with a non-empty ``claim_id`` (a finding published through AD-1140's governed route) or
      whose status is ``published``: a notebook finding.
```
REPLACE:
```python
    - ``notebooks/`` with a non-empty ``claim_id`` (a finding published through AD-1140's governed route) or
      whose status is ``published``: a notebook finding.
    - ``exit-notes/`` (AD-1341 S4): an exit note. Its own rule, ``_exit_note_record``, applies when it is read.
```

Pair 4 (the criterion):

SEARCH:
```python
    if type(frontmatter) is not dict:
        return None
    author = frontmatter.get("author")
```
REPLACE:
```python
    if type(frontmatter) is not dict:
        return None
    if path.startswith(f"{EXIT_NOTES_DIR}/"):
        return SourceKind.EXIT_NOTE  # AD-1341 S4: every exit note is a source; _exit_note_record withholds a bad one
    author = frontmatter.get("author")
```

Pair 5 (the exit-note rule and the erasure's read, before `PromotionPlan`):

SEARCH:
```python
@dataclass(frozen=True)
class PromotionPlan:
```
REPLACE:
```python
def _exit_note_record(path: str, document: Any) -> PromotionRecord | None:
    """AD-1341 S4: an exit note as the Ship's Archive receives it, or None when it breaks the exit-note rule (D7, D9).

    The rule: the ``exit_note`` envelope (version 1, an ``int``) names a timeline, a callsign, an agent type and the
    author's DID, each one line within its bound (``exit_note_provenance_ok``), and lists at most
    ``LESSON_MAX_CITATIONS`` distinct episode ids, each one line within its bound; the path is the one
    ``exit_note_path`` gives for that timeline and agent type; the author is the callsign; the body is exactly the
    note's origin line followed by a canonical lesson (``exit_note_lesson``), so what is archived is what the Captain
    reviewed and what the rule parsed (A2); the classification is ``ship`` or ``fleet`` (C1). The entry is attributed
    to the timeline that wrote the note, not to the reset that promotes it, so a note a skipped promotion left behind
    keeps its own generation.

    Never raises for a document: every value ``PromotionRecord`` would refuse is checked here first, and a stored
    value ``str()`` cannot convert is archived as no value (``_stored_text``, A5), so one bad note is withheld or
    archived and never stops a reset (S1 A3's rule). The one rule for the promotion and for ``exit_note_citations``.
    """
    if type(document) is not dict or type(document.get("frontmatter")) is not dict:
        return None
    frontmatter, content = document["frontmatter"], document.get("content")
    envelope = frontmatter.get(EXIT_NOTE_KEY)
    if type(envelope) is not dict:
        return None
    version = envelope.get("version")
    if type(version) is not int or version != EXIT_NOTE_VERSION:  # A2: True and 1.0 equal 1 and are not it
        return None
    named = [envelope.get(field) for field in ("timeline_id", "callsign", "agent_type", "author_did")]
    if not exit_note_provenance_ok(*named):  # A2: one storable line each, within its bound
        return None
    note_timeline, callsign, agent_type, author_did = named
    cited = envelope.get("source_episode_ids")
    if type(cited) is not list or not all(is_exit_note_text(item, EXIT_NOTE_EPISODE_ID_MAX_CHARS) for item in cited):
        return None
    if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):
        return None
    try:
        expected_path = exit_note_path(note_timeline, agent_type)
    except ValueError:
        return None
    if path != expected_path or frontmatter.get("author") != callsign:
        return None
    if exit_note_lesson(callsign, agent_type, note_timeline, content) is None:
        return None  # A2: the body is exactly the origin line and a canonical lesson, or nothing is archived
    classification = frontmatter.get("classification")
    if type(classification) is not str or classification not in PROMOTABLE_CLASSIFICATIONS:
        return None  # C1: nothing narrower than ship reaches a later crew
    return PromotionRecord(
        timeline_id=note_timeline,  # AD-1341 S4 (D9): the timeline that wrote the note, not the reset's
        source_kind=SourceKind.EXIT_NOTE,
        source_ref=path,
        title=f"Exit notes of {callsign}",
        content=content,
        classification=classification,
        author_callsign=callsign,
        author_agent_type=agent_type,
        author_did=author_did,
        source_episode_ids=tuple(cited),  # AD-1341 S4: the agent's own episodes, by id; never their text
        metadata={  # A5 (R3-M1-2): each stored value through the one never-raising conversion
            "status": _stored_text(frontmatter.get("status")),
            "record_created": _stored_text(frontmatter.get("created")),
            "record_updated": _stored_text(frontmatter.get("updated")),
        },
    )


async def exit_note_citations(records: RecordsStore, archive: ArchiveStore | None) -> dict[str, tuple[str, ...]]:
    """AD-1341 S4 (D14): each episode id cited by an exit note the next promotion would archive, with those notes.

    The notes are read as the promotion reads them (``_exit_note_record``, the one rule). With an open archive a note
    counts while ``source_state`` says CREATED; a vetoed, erased or already archived note does not (an archived one
    is S3's own check). With no open archive every valid note counts (fail closed: the next reset opens the archive
    and would promote it). Reads Ship's Records and the archive; writes nothing; any failure propagates.

    A2 (M1-F1, M3-F1): the listing is strict, so a note file that exists but cannot be read now (a sharing violation, a
    permission, an I/O error) raises instead of being skipped as if it were not there. A file whose bytes are not
    UTF-8, or whose frontmatter does not parse, is never counted, because the promotion never archives it either: that
    is a property of the file, not of the moment.

    A5 (7.3a's table, O6): each listed note is read again through ``read_entry``, whose ``Path.exists`` answers False
    for errors ``pathlib`` reads as "not there". A ship-wide note the strict listing returned and the second read
    cannot find raises: it was there a moment ago, so whether the next promotion would archive it is unknown.
    """
    citing: dict[str, list[str]] = {}
    for listed in await records.list_entries(EXIT_NOTES_DIR, strict=True):
        path = listed["path"]
        if source_kind_for(path, listed["frontmatter"]) is not SourceKind.EXIT_NOTE:
            continue  # plan_promotion skips it unread (frontmatter not a mapping), so it can never be archived
        document = await records.read_entry(path, ARCHIVE_READER)
        classification = listed["frontmatter"].get("classification")
        listed_readable = type(classification) is str and classification in PROMOTABLE_CLASSIFICATIONS
        if document is None and listed_readable:  # A5 (O6): listed a moment ago, not found now: never "no citations"
            raise OSError(f"AD-1341 S4: the exit note {path} was listed but cannot be found now")
        record = _exit_note_record(path, document)
        if record is None or not record.source_episode_ids:
            continue
        if archive is not None and (await archive.source_state(record)).outcome is not PromotionOutcome.CREATED:
            continue
        for episode_id in record.source_episode_ids:
            citing.setdefault(episode_id, []).append(path)
    return {episode_id: tuple(paths) for episode_id, paths in citing.items()}


@dataclass(frozen=True)
class PromotionPlan:
```

Pair 6 (the plan reads an exit note by its own rule):

SEARCH:
```python
        if document is None:
            withheld.append(path)
            continue
        frontmatter = document["frontmatter"]
```
REPLACE:
```python
        if document is None:
            withheld.append(path)
            continue
        if path.startswith(f"{EXIT_NOTES_DIR}/"):  # AD-1341 S4: an exit note carries its own provenance
            note = _exit_note_record(path, document)
            if note is None:
                withheld.append(path)
            else:
                selected.append(note)
            continue
        frontmatter = document["frontmatter"]
```

Pair 7 (the plan's docstring, A2, M1-F9):

SEARCH:
```python
    """The records a run would promote, attributed to ``timeline_id``. Reads Ship's Records; writes nothing.

    ``probos reset --dry-run`` lists this plan. A document is withheld when the anonymous read refuses it, when
    its body is empty, or when it is narrower than ``ship`` (C1: a later crew reads every archived entry). An
    empty ``timeline_id`` raises as soon as there is anything to promote. A blank topic withholds nothing: the title
    falls back to the file name, then the records path (A3, F1).
    """
```
REPLACE:
```python
    """The records a run would promote, attributed to ``timeline_id``. Reads Ship's Records; writes nothing.

    ``probos reset --dry-run`` lists this plan. A document is withheld when the anonymous read refuses it, when
    its body is empty, or when it is narrower than ``ship`` (C1: a later crew reads every archived entry). An
    empty ``timeline_id`` raises as soon as there is anything to promote. A blank topic withholds nothing: the title
    falls back to the file name, then the records path (A3, F1).

    AD-1341 S4: an exit note (``exit-notes/``) is the exception to both. ``_exit_note_record`` attributes it to the
    timeline in its own envelope, never to ``timeline_id``, and a valid note never raises for an empty
    ``timeline_id`` (the CLI refuses a run without an instance id before it plans). A note that breaks the rule is
    withheld. The listing is not strict: a file that cannot be read at this moment is skipped, as S1 left it.
    """
```

Pair 8 (A5, round 3 R3-M1-2: one never-raising conversion for every stored value; the title through it):

SEARCH:
```python
def _title_for(path: str, frontmatter: dict[str, Any]) -> str:
    """The archive entry's title: the document's topic, else its file name, else its records path (A3, F1).

    The producers accept a blank topic (``write_entry(topic="   ")``, ``write_notebook(topic_slug=" ")``) and the
    promotion record refuses a blank title. A title is a label, so it never withholds a document or stops a run.
    The records path is never blank: only a path under a source's directory is a source.
    """
    topic = frontmatter.get("topic")
    for candidate in (str(topic) if topic else "", path.rsplit("/", 1)[-1].removesuffix(".md")):
```
REPLACE:
```python
def _stored_text(value: object) -> str:
    """AD-1341 S4 (A5, round 3 R3-M1-2): a stored frontmatter value as archive text; never raises.

    ``str()`` raises ``ValueError`` for an integer longer than Python's integer-string limit (4,300 digits by default,
    ``sys.set_int_max_str_digits``), which YAML builds from ``0x...``; one such value stopped the plan and the whole
    reset. It is archived as no value, as a missing one is. Every other value converts exactly as ``str()`` did.
    """
    try:
        return str(value or "")
    except ValueError:  # A5 (R3-M1-2): an integer longer than Python's integer-string limit
        logger.warning("AD-1341 S4: a stored Ship's Records value cannot be shown as text; it is archived empty")
        return ""


def _title_for(path: str, frontmatter: dict[str, Any]) -> str:
    """The archive entry's title: the document's topic, else its file name, else its records path (A3, F1).

    The producers accept a blank topic (``write_entry(topic="   ")``, ``write_notebook(topic_slug=" ")``) and the
    promotion record refuses a blank title. A title is a label, so it never withholds a document or stops a run.
    The records path is never blank: only a path under a source's directory is a source.
    """
    topic = frontmatter.get("topic")
    for candidate in (_stored_text(topic), path.rsplit("/", 1)[-1].removesuffix(".md")):
```

Pair 9 (A5: S1's record converts its stored values the same way; they were the same `ValueError` on the base):

SEARCH:
```python
                author_callsign=str(frontmatter.get("author") or ""),
                metadata={
                    "status": str(frontmatter.get("status") or ""),
                    "department": str(frontmatter.get("department") or ""),
                    "record_created": str(frontmatter.get("created") or ""),
                    "record_updated": str(frontmatter.get("updated") or ""),
                },
```
REPLACE:
```python
                author_callsign=_stored_text(frontmatter.get("author")),
                metadata={  # AD-1341 S4 (A5): S1's conversions, through the one never-raising rule
                    "status": _stored_text(frontmatter.get("status")),
                    "department": _stored_text(frontmatter.get("department")),
                    "record_created": _stored_text(frontmatter.get("created")),
                    "record_updated": _stored_text(frontmatter.get("updated")),
                },
```

### 7.3a `src/probos/knowledge/records_store.py` (M1, A2)

A2 (M1-F1, M3-F1). `list_entries` (`:961-1001`) catches every read or parse failure of a listed file and skips it (`:982-987`), so a caller cannot tell an unreadable note from an absent one. `strict=True` re-raises an `OSError` reading a regular file that exists. A file that is not UTF-8 is still skipped (a property of the file; the promotion skips it too); a YAML error never reaches here (`_parse_document`, `:1190-1200`, folds it into `{}`); a path that is no longer a file (a directory named `*.md`, a vanished file) is skipped as absent. The default keeps every caller's behaviour (§5). A shared contract: round 2 re-reviews whole.

A4 (R2-F1, M3-1). `Path.rglob` (`:984`) also passes over a directory it cannot list, so a strict reader still took the notes inside an unlistable `exit-notes/` or timeline directory for absent ones. `strict=True` now walks with `os.walk` and an error callback that re-raises for a directory that exists but cannot be listed, and treats a directory that does not exist (or is gone) as empty (pairs 3 to 5). The default runs the same `rglob` call as before. Round 3 re-reviews whole.

A5 (round 3 R3-M1-1, and its class). `os.walk` catches an `OSError` from `DirEntry.is_dir()` and files the entry as a non-directory (CPython 3.12 `Lib/os.py:386-399`), so a timeline directory whose type could not be read was never descended, and the strict listing returned `[]` without raising. Round 2 found the same hole in `Path.rglob` at the directory open. Each standard walker absorbs some error, so A5 replaces the walker and decides every filesystem operation of the strict read once (pairs 2 and 4 here; 7.3 pair 5; 7.6). The rule: **only a successful listing proves that a document is not there.**

| # | Operation | Failure | Disposition |
|---|---|---|---|
| O1 | `os.scandir(search_path)` | `FileNotFoundError`, `NotADirectoryError` | `[]`: nothing was written under a directory that is not there |
| O1 | | any other `OSError` | raises |
| O2 | `os.scandir` of a directory a listing reported | any `OSError`, `FileNotFoundError` included | raises: gone since, or unaddressable, it is not proved empty; the strict caller refuses and is retried |
| O3 | each step of a listing, the last included | any `OSError` | raises |
| O4 | `entry.is_dir(follow_symlinks=False)` | any `OSError` | raises; never taken for a file (the type comes from the listing record: a symbolic link is not descended, as `rglob` descends none; a junction is) |
| O5 | `md_file.read_text` in `list_entries(strict=True)` | any `OSError` | raises, with no second look: A2's `md_file.is_file()` read EBADF, ELOOP, ENOENT, ENOTDIR and "the device is not ready" as "not there" |
| O5 | | `UnicodeDecodeError` | skipped (A2: a property of the file) |
| O6 | `read_entry` in `exit_note_citations` (`Path.exists`, then `read_text`) | None for a note the listing returned with a `ship` or `fleet` classification | raises (7.3 pair 5) |
| O6 | | an `OSError` from `exists` or `read_text` | propagates (unchanged) |
| O7 | the stand-down's check of a billet (`_present`: `Path.lstat`) | `FileNotFoundError`, `NotADirectoryError` | nothing there |
| O7 | | any other `OSError` | unknown: the guard writes nothing (`failed`, no path) and `_left_at` names the path |

The walk returns files only: a directory named `*.md` is never a document. It was listed and then skipped before; `list_entries` lists the same (C3f). Outside the table, each decided in register R31: `_safe_path`'s `resolve()`, a missing root the OS cannot address, special files, a junction cycle, the default listing and the reviews built on it (R20), git (R23), `write_entry`'s own `exists()` (R28) and the one-snapshot bound (R2). C3g is a trace-and-fault matrix over O1 to O4; C3h faults O5; C3i faults O6; S8d, S2c and S4d run O7; C3e, S8c and X8 cross the strict read's two consumers. A shared contract: round 4 reviews the delta with this table as its property (§14, 16).

Pair 1 (the parameter):

SEARCH:
```python
        tags: list[str] | None = None,
        classification: str = "",
    ) -> list[dict]:
        """List documents with optional filters.

        Returns list of {"path": ..., "frontmatter": {...}} dicts.
        """
```
REPLACE:
```python
        tags: list[str] | None = None,
        classification: str = "",
        strict: bool = False,
    ) -> list[dict]:
        """List documents with optional filters.

        Returns list of {"path": ..., "frontmatter": {...}} dicts.

        A file that cannot be read is skipped and logged at debug. AD-1341 S4 (A2): ``strict=True`` re-raises an
        ``OSError`` reading a listed regular file instead (a sharing violation, a permission, an I/O error: the file
        exists but cannot be read now), for a caller that must not take an unreadable document for an absent one (the
        AD-754 erasure's read of pending exit notes, and the stand-down). Bytes that are not UTF-8 are still skipped:
        that is a property of the file, not of the moment. ``False`` (the default) keeps every other caller unchanged.
        A4, A5: ``strict=True`` walks with ``_markdown_files_or_raise``, which raises every ``OSError`` that could leave
        a document unseen (a directory it cannot open, a listing step that fails, an entry whose type it cannot read)
        and reads only a missing ``directory`` as empty. A listed file whose read fails raises for any ``OSError``,
        with no second look at whether it is still a file (A5).
        """
```

Pair 2 (the read):

SEARCH:
```python
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
            except Exception:
                logger.debug("Skipping unreadable file", exc_info=True)
                continue
```
REPLACE:
```python
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
            except OSError:
                if strict:  # A5 (O5): a file the walk listed is never "no document", whatever the read's error
                    raise  # AD-1341 S4 (A2): a file that exists but cannot be read now is never "no document"
                logger.debug("Skipping unreadable file", exc_info=True)
                continue
            except Exception:
                logger.debug("Skipping unreadable file", exc_info=True)
                continue
```

Pair 3 (A4: the modules the strict walk uses):

SEARCH:
```python
import asyncio
import logging
import subprocess
```
REPLACE:
```python
import asyncio
import fnmatch
import logging
import os
import subprocess
```

Pair 4 (A4: the strict walk, a module function beside `_jaccard_similarity`):

SEARCH:
```python
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class RecordsStore:
```
REPLACE:
```python
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _markdown_files_or_raise(search_path: Path) -> list[Path]:
    """AD-1341 S4 (A4, A5): every file named ``*.md`` under ``search_path``, or the ``OSError`` that hid one.

    A5 (round 3 R3-M1-1): ``os.walk`` filed an entry whose type it could not read as a file and never descended into
    it, as ``Path.rglob`` passed over a directory it could not list (A4): each standard walker absorbs some error. So
    this walk is explicit, and each filesystem operation it makes has one disposition (the contract's 7.3a table):

    - O1 ``os.scandir(search_path)``: ``FileNotFoundError`` or ``NotADirectoryError`` lists nothing, since nothing
      was written under a directory that is not there; any other ``OSError`` raises.
    - O2 ``os.scandir`` of a directory a listing reported: any ``OSError`` raises, ``FileNotFoundError`` included
      (gone since, or unaddressable, it is not proved empty; a strict caller refuses and is retried).
    - O3 each step of a listing: any ``OSError`` raises.
    - O4 ``entry.is_dir(follow_symlinks=False)``: any ``OSError`` raises; the entry is never taken for a file. The
      type comes from the listing record, so a symbolic link is not descended, as ``rglob`` descends none.

    Only a successful listing proves a document absent. A directory named ``*.md`` is no document and is not
    returned; the suffix matches with the platform's case rule (``fnmatch``), as ``rglob``'s does.
    """
    found: list[Path] = []
    pending: list[Path] = [search_path]
    while pending:
        directory = pending.pop()
        try:
            listing = os.scandir(directory)  # O1 for search_path, O2 below it
        except (FileNotFoundError, NotADirectoryError):
            if directory is not search_path:
                raise  # O2 (A5): a directory a listing reported is never "no documents"
            return found  # O1: search_path does not exist, so nothing was written under it
        with listing:
            for entry in listing:  # O3: an OSError while listing propagates
                path = Path(directory, entry.name)
                if entry.is_dir(follow_symlinks=False):  # O4: an OSError propagates; it is never read as "a file"
                    pending.append(path)
                elif fnmatch.fnmatch(entry.name, "*.md"):
                    found.append(path)
    return found


class RecordsStore:
```

Pair 5 (A4: the strict listing walks with it; the default runs the same `rglob` call):

SEARCH:
```python
        search_path = self._safe_path(directory) if directory else self._repo_path
        results = []

        for md_file in sorted(search_path.rglob("*.md")):
```
REPLACE:
```python
        search_path = self._safe_path(directory) if directory else self._repo_path
        results = []
        # AD-1341 S4 (A4): rglob passes over a directory it cannot list; the strict walk raises its OSError instead
        found = _markdown_files_or_raise(search_path) if strict else search_path.rglob("*.md")

        for md_file in sorted(found):
```

### 7.4 `tests/test_ad1341_s1_archive_store.py` (M1: K1 pins the closed set)

SEARCH:
```python
def test_source_kinds_are_closed_and_none_is_an_episode() -> None:
    assert {kind.value for kind in SourceKind} == {
        "convergence_report", "published_report", "captains_log", "notebook_finding",
    }
```
REPLACE:
```python
def test_source_kinds_are_closed_and_none_is_an_episode() -> None:
    # AD-1341 S4 (#1569): the exit note joins the closed set. It is a lesson a crew agent writes for its successor and
    # cites that agent's episodes by id; it is not an episode, so the assertion below still holds.
    assert {kind.value for kind in SourceKind} == {
        "convergence_report", "published_report", "captains_log", "notebook_finding", "exit_note",
    }
```

### 7.4a `tests/test_ad1341_s1_promotion.py` (M1: K2, S1's census of the service's imports)

A1. S1 pins the exact `probos.*` imports of `archive_promotion.py` (`:413-420`). 7.3 pair 2 adds `probos.knowledge.lessons`, a module of the same layer, so the pinned set gains it. The orchestrator found it by running M1's gate on the A0 draft (1 failed: `Extra items in the left set: 'probos.knowledge.lessons'`). No mutation row: the census checks the source, and 7.3's import is what it now pins.

SEARCH:
```python
def test_the_service_imports_only_the_knowledge_layer() -> None:
    tree = ast.parse((_SRC / "knowledge" / "archive_promotion.py").read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert {name for name in modules if name.split(".")[0] == "probos"} == {
        "probos.knowledge.archive_store",
        "probos.knowledge.records_store",
    }
```
REPLACE:
```python
def test_the_service_imports_only_the_knowledge_layer() -> None:
    tree = ast.parse((_SRC / "knowledge" / "archive_promotion.py").read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    # AD-1341 S4 (#1569): the exit note's rule reads the lessons format (``probos.knowledge.lessons``), a module of the
    # same knowledge layer, so the service still imports only that layer.
    assert {name for name in modules if name.split(".")[0] == "probos"} == {
        "probos.knowledge.archive_store",
        "probos.knowledge.lessons",
        "probos.knowledge.records_store",
    }
```

### 7.5 New file: `tests/test_ad1341_s4_lessons.py` (M1)

```python
"""AD-1341 S4 M1 (#1569): the lessons format, and an exit note promoted into the Ship's Archive with its provenance.

Real objects throughout: the real parser and renderer; Ship's Records written by the store's own ``write_entry``
(S1's ``_records``, no git); the real promotion service, S3's review and the citation read; the real ``ArchiveStore``
with S3's veto and S1's erasure. ``_write_note`` writes a note as ``probos.stand_down`` writes one, and each of its
keywords breaks one part of the rule; M2's tests write notes through the stand-down itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge.archive_promotion import (
    exit_note_citations,
    plan_promotion,
    promote_ship_records,
    review_promotion,
)
from probos.knowledge.archive_store import PromotionOutcome, SourceKind, VetoOutcome
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_AGENT_TYPE_MAX_CHARS,
    EXIT_NOTE_CALLSIGN_MAX_CHARS,
    EXIT_NOTE_DID_MAX_CHARS,
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_TIMELINE_MAX_CHARS,
    EXIT_NOTE_VERSION,
    EXIT_NOTES_DIR,
    LESSON_MAX_CHARS,
    LESSON_MAX_CITATIONS,
    LESSON_SECTIONS,
    LessonLearned,
    exit_note_body,
    exit_note_header,
    exit_note_path,
    exit_notes_directory,
    is_declined,
    is_exit_note_text,
    parse_citations,
    parse_lesson,
)
from probos.knowledge.records_store import RecordsStore, _markdown_files_or_raise
from probos.tools.oracle_query_tool import _MAX_ENTRY_CHARS, OracleQueryTool
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _NEXT_SHIP, _SHIP, _config, _data_dir, _records, _reset

_DID = f"did:probos:{_SHIP}:chapel-0001"
_LESSON = LessonLearned(
    observation="The coolant drift alarm fired three times on the night watch before anyone traced it.",
    discussion=(
        "Lesson learned, the hard way: each watch read the alarm as noise because the last had cleared it unlogged."
    ),
    lesson="An alarm cleared without a written cause teaches the next watch to ignore it.",
    recommendation="Log the cause of every cleared alarm, and trace any alarm that repeats a third time.",
)


def _sections() -> tuple[tuple[str, str], ...]:
    bodies = (_LESSON.observation, _LESSON.discussion, _LESSON.lesson, _LESSON.recommendation)
    return tuple(zip(LESSON_SECTIONS, bodies, strict=True))


async def _write_note(
    records: RecordsStore,
    *,
    timeline: str = _SHIP,
    agent_type: str = "surgeon",
    callsign: str = "Chapel",
    did: str = _DID,
    cited: tuple[str, ...] = ("ep-000",),
    envelope: dict[str, Any] | None = None,
    with_envelope: bool = True,
    content: str | None = None,
    path: str | None = None,
    author: str | None = None,
    classification: str = "ship",
    lesson: LessonLearned = _LESSON,
) -> str:
    """An exit note written as ``probos.stand_down`` writes one; each keyword breaks one part of the rule."""
    note_path = path or exit_note_path(timeline, agent_type)
    fields: dict[str, Any] = {
        "version": EXIT_NOTE_VERSION, "timeline_id": timeline, "callsign": callsign, "agent_type": agent_type,
        "author_did": did, "source_episode_ids": list(cited),
    }
    fields.update(envelope or {})
    await records.write_entry(
        author=callsign if author is None else author,
        path=note_path,
        content=exit_note_body(callsign, agent_type, timeline, lesson) if content is None else content,
        message=f"test: exit notes of {callsign}",
        classification=classification,
        status=EXIT_NOTE_STATUS,
        topic=f"Exit notes of {callsign}",
        tags=["exit-notes", "ad-1341"],
        extra_frontmatter={EXIT_NOTE_KEY: fields} if with_envelope else None,
    )
    return note_path


def _deny_reading(monkeypatch: pytest.MonkeyPatch, denied: Path, error: OSError | None = None) -> None:
    """A2: the OS refuses to read ``denied``, as a sharing violation does while an editor or a scanner holds the file.

    Only ``Path.read_text`` of that one file fails, so the real ``RecordsStore.list_entries`` meets the failure inside
    its own loop, on every platform. A5: ``error`` is the failure raised (a sharing violation by default).
    """
    real_read_text = Path.read_text
    target = denied.resolve()

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.resolve() == target:
            if error is not None:
                raise error
            raise PermissionError(13, "the file is being used by another process", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)


@contextlib.contextmanager
def _unreadable(path: Path) -> Iterator[None]:
    """A2: the OS itself refuses to read ``path`` while this is open: a handle that shares nothing on Windows, mode 000
    elsewhere. Skips where this account reads such a file anyway (root on POSIX). A4: ``path`` may be a directory,
    which the OS then refuses to list."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        flags = 0x02000000 if path.is_dir() else 0x80  # A4: FILE_FLAG_BACKUP_SEMANTICS opens a directory
        handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, flags, None)  # GENERIC_READ, share nothing
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel32.CloseHandle(handle)
    else:
        directory, mode = path.is_dir(), path.stat().st_mode
        path.chmod(0)
        try:
            try:
                if directory:
                    os.listdir(path)  # A4: a directory with mode 000 cannot be listed
                else:
                    path.read_text(encoding="utf-8")
            except PermissionError:
                pass
            else:
                pytest.skip("this account reads a file with mode 000 (root): no native read denial to test")
            yield
        finally:
            path.chmod(mode)


def _deny_listing(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """A4 (R2-F1, M3-1): the OS refuses to list the directory ``denied``, as a sharing violation does.

    Only ``os.scandir`` of that one directory fails, so the real traversal inside ``RecordsStore.list_entries`` meets
    the failure itself, on every platform. (Python 3.13's ``glob`` may bind ``scandir`` at import, so the default
    listing's result under this patch is not asserted; the native cases assert it.)
    """
    real_scandir = os.scandir
    target = denied.resolve()

    def scandir(path: Any = ".") -> Any:
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == target:
            raise PermissionError(13, "the directory is being used by another process", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)


def _deny_entry_type(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """A5 (round 3 R3-M1-1): the OS cannot report the type of the entry ``denied`` when its parent is listed
    (``DirEntry.is_dir`` raises), as for a link whose target cannot be examined or a filesystem that reports no
    types. ``os.walk`` filed such an entry as a file and never descended into it. Every listing passes through a
    wrapper; only that one entry's ``is_dir`` fails, and every other attribute is the real entry's."""
    real_scandir = os.scandir
    target = denied.resolve()

    class _Entry:
        def __init__(self, entry: Any) -> None:
            self._entry = entry

        def __getattr__(self, name: str) -> Any:
            return getattr(self._entry, name)

        def is_dir(self, *args: Any, **kwargs: Any) -> bool:
            if Path(self._entry.path).resolve() == target:
                raise PermissionError(13, "the entry's type cannot be read", self._entry.path)
            return bool(self._entry.is_dir(*args, **kwargs))

    class _Listing:
        def __init__(self, listing: Any) -> None:
            self._listing = listing

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: object) -> None:
            self._listing.close()

        def __iter__(self) -> Any:
            return self

        def __next__(self) -> _Entry:
            return _Entry(next(self._listing))

        def close(self) -> None:
            self._listing.close()

    def scandir(path: Any = ".") -> Any:
        return _Listing(real_scandir(path))

    monkeypatch.setattr(os, "scandir", scandir)


def _deny_stat(monkeypatch: pytest.MonkeyPatch, denied: Path, error: OSError) -> None:
    """A5: ``Path.stat`` of ``denied`` fails with ``error``. ``Path.exists`` and ``Path.is_file`` read ENOENT, ENOTDIR,
    EBADF and ELOOP, and three Windows errors ("the device is not ready" among them), as "not there". Compared by
    name, never through ``resolve()``, which calls ``stat`` itself."""
    real_stat = Path.stat
    target = os.path.normcase(os.fspath(denied.resolve()))

    def stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if os.path.normcase(os.fspath(self)) == target:
            raise error
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)


#: A5: the failures 7.3a's table decides, by kind.
_WALK_FAULTS: dict[str, Any] = {
    "absent": lambda where: FileNotFoundError(errno.ENOENT, "gone", where),
    "io": lambda where: OSError(errno.EIO, "I/O error", where),
    "not-a-directory": lambda where: NotADirectoryError(errno.ENOTDIR, "not a directory", where),
    "permission": lambda where: PermissionError(errno.EACCES, "denied", where),
}


class _Trace:
    """A5: the strict walk's filesystem operations in order; with ``fail_at``, that one (1-based) raises ``fault``."""

    def __init__(self, fail_at: int = 0, fault: Any = None) -> None:
        self.operations: list[str] = []
        self.fail_at, self.fault, self.fired = fail_at, fault, ""

    def tick(self, operation: str, where: str) -> None:
        self.operations.append(operation)
        if len(self.operations) == self.fail_at:
            self.fired = operation
            raise self.fault(where)


class _TracedEntry:
    """A5: a directory entry offering only ``name`` and ``is_dir``: 7.3a's table has no row for anything else."""

    def __init__(self, entry: Any, trace: _Trace) -> None:
        self.name: str = entry.name
        self._entry, self._trace = entry, trace

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        assert follow_symlinks is False, "O4 reads the listing record and never follows a link"
        self._trace.tick("is_dir", self._entry.path)
        return bool(self._entry.is_dir(follow_symlinks=False))


class _TracedListing:
    """A5: one traced ``os.scandir`` listing; each step is an operation, the step that ends the listing included."""

    def __init__(self, listing: Any, trace: _Trace, where: str) -> None:
        self._listing, self._trace, self._where = listing, trace, where

    def __enter__(self) -> _TracedListing:
        return self

    def __exit__(self, *exc: object) -> None:
        self._listing.close()

    def __iter__(self) -> _TracedListing:
        return self

    def __next__(self) -> _TracedEntry:
        self._trace.tick("next", self._where)
        return _TracedEntry(next(self._listing), self._trace)


def _traced_walk(root: Path, trace: _Trace) -> list[Path]:
    """A5: the real ``_markdown_files_or_raise`` with every ``os.scandir`` traced, and a tripwire on every other
    filesystem call it could make, so an operation without a row in 7.3a's table fails the test."""
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> _TracedListing:
        where = os.fspath(path)
        trace.tick("open-root" if Path(where) == root else "open-subdirectory", where)
        return _TracedListing(real_scandir(path), trace, where)

    def tripwire(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the strict walk made a filesystem call that 7.3a's table has no row for")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "scandir", scandir)
        for name in ("stat", "lstat", "listdir", "walk"):
            patch.setattr(os, name, tripwire)
        return _markdown_files_or_raise(root)


def _walk_tree(root: Path) -> None:
    """A5: every shape the walk meets: nested directories, two timelines, a directory named ``*.md``, another suffix
    and the suffix in upper case."""
    for relative in (
        "ship-a/surgeon.md", "ship-a/chapel.md", "ship-b/deep/er/nested.md", "ship-b/UPPER.MD", "ship-b/plain.txt",
        "top.md",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("---\nauthor: Bones\n---\n\nA record.\n", encoding="utf-8")
    (root / "folder.md").mkdir()


# --- L1 to L7: the format -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lesson",
    [
        _LESSON,
        LessonLearned("Two lines\nof observation.", "A discussion\n\n  with an indented paragraph.", "One.", "Two."),
    ],
    ids=["one-line", "multi-line"],
)
def test_a_rendered_lesson_parses_back_to_itself(lesson: LessonLearned) -> None:
    rendered = lesson.render()

    assert rendered.startswith("## Observation\n\n")
    assert [line for line in rendered.splitlines() if line.startswith("## ")] == [f"## {n}" for n in LESSON_SECTIONS]
    assert parse_lesson(rendered) == lesson


_FORMS: dict[str, str] = {
    "markdown": _LESSON.render(),
    "markdown-colon": "\n".join(f"### {name}:\n{body}" for name, body in _sections()),
    "bold": "\n".join(f"**{name}**\n{body}" for name, body in _sections()),
    "plain": "\n".join(f"{name}\n{body}" for name, body in _sections()),
    "label": "\n".join(f"{name}: {body}" for name, body in _sections()),
    "bold-label": "\n".join(f"**{name}:** {body}" for name, body in _sections()),
    "preamble-and-cites": f"Here are my notes.\n\n{_LESSON.render()}\nCites: e1, e2\n",
}


@pytest.mark.parametrize("form", sorted(_FORMS))
def test_the_four_sections_are_read_in_each_heading_form(form: str) -> None:
    # _LESSON's discussion opens "Lesson learned, the hard way:": a sentence, never a heading (a label needs its colon).
    assert parse_lesson(_FORMS[form]) == _LESSON


_CLOSURE: dict[str, str] = {
    **_FORMS,
    "label-inline-heading": "Observation: Discussion: the cause\nDiscussion: d\nLesson: l\nRecommendation: r",
    "label-inline-cites": "Observation: Cites: e1\nDiscussion: d\nLesson: l\nRecommendation: r",
    "label-inline-bold-name": "Observation: **Lesson**\nDiscussion: d\nLesson: l\nRecommendation: r",
    "indented-name": "## Observation\n    Discussion\n## Discussion\nd\n## Lesson\nl\n## Recommendation\nr",
}
_REFUSED_FOR_CLOSURE = {"label-inline-heading", "label-inline-cites", "label-inline-bold-name", "indented-name"}


@pytest.mark.parametrize("case", sorted(_CLOSURE))
def test_every_lesson_the_parser_accepts_is_written_and_read_back_unchanged(case: str) -> None:
    """A2 (M1-F3): the format is closed under ``render``. A section that would read as a heading or a ``Cites:`` line
    once rendered on its own line is refused; every accepted lesson renders, and is stored, as text that parses back
    to itself."""
    lesson = parse_lesson(_CLOSURE[case])

    if case in _REFUSED_FOR_CLOSURE:
        assert lesson is None
    else:
        assert lesson is not None
        assert parse_lesson(lesson.render()) == lesson
        assert parse_lesson(exit_note_body("Chapel", "surgeon", _SHIP, lesson)) == lesson


_NOT_LESSONS: dict[str, object] = {
    "missing": "\n\n".join(f"## {name}\n\n{body}" for name, body in _sections()[:3]),
    "reordered": "\n\n".join(f"## {name}\n\n{body}" for name, body in (_sections()[1], _sections()[0], *_sections()[2:])),
    "repeated": f"{_LESSON.render()}\n\n## Lesson\n\nAnd once more.",
    "empty-section": "## Observation\n\n## Discussion\nd\n## Lesson\nl\n## Recommendation\nr",
    "too-long": LessonLearned("o" * (LESSON_MAX_CHARS - 2), "d", "l", "r").render(),  # 701 in all (A2)
    "nul": _LESSON.render().replace("cleared", "clea\x00red"),  # A2: SQLite cannot store it whole
    "surrogate": _LESSON.render() + "\ud800",
    # A4 (R2-F5): what a console acts on; the Captain reads notes at a terminal.
    "escape": _LESSON.render().replace("cleared", "\x1b[2Jcleared"),
    "bell": _LESSON.render().replace("cleared", "\x07cleared"),
    "c1-control": _LESSON.render().replace("cleared", "\x9bcleared"),
    "delete": _LESSON.render().replace("cleared", "\x7fcleared"),
    "vertical-tab": _LESSON.render().replace("night watch", "night\x0bwatch"),
    "prose": "I learned a great deal on this voyage, and I leave it all to my successor.",
    "not-text": 42,
}


@pytest.mark.parametrize("case", sorted(_NOT_LESSONS))
def test_a_reply_not_in_the_format_is_no_lesson(case: str) -> None:
    assert parse_lesson(_NOT_LESSONS[case]) is None


_ASCII_LETTER = re.compile("[a-z]", re.IGNORECASE)


def test_a_section_name_spelled_with_a_lookalike_letter_opens_no_section() -> None:
    """A4 (R2-F2): under Unicode IGNORECASE four letters outside ASCII match as ASCII ones (the dotted capital I, the
    dotless i, the long s, the Kelvin sign), and the section lookup held only ASCII names, so such a heading raised
    ``KeyError`` through the parser, the rule and the plan. The section names now match in ASCII only: every such
    spelling of every section, in every heading form, opens no section, and the reply is refused, never raised."""
    lookalikes = [
        chr(code) for code in range(0x80, 0x110000)
        if not 0xD800 <= code <= 0xDFFF and _ASCII_LETTER.fullmatch(chr(code))
    ]
    assert lookalikes == ["\u0130", "\u0131", "\u017f", "\u212a"]  # premise: Python's documented four
    cases = [
        (name, name[:index] + char + name[index + 1:])
        for name in LESSON_SECTIONS
        for index, letter in enumerate(name.lower())
        for char in lookalikes
        if re.fullmatch(letter, char, re.IGNORECASE)
    ]
    assert len(cases) == 14  # premise: Observation 3, Discussion 7, Lesson 2, Recommendation 2
    for name, variant in cases:
        for heading in (f"## {variant}", f"**{variant}**", variant, f"{variant}: text"):
            assert parse_lesson(_LESSON.render().replace(f"## {name}", heading, 1)) is None, (variant, heading)


def test_a_lesson_carries_no_control_character_but_tab_line_feed_and_carriage_return() -> None:
    """A4 (R2-F5): the Captain reads exit notes at a console, where an escape sequence acts. Every C0 and C1 control
    and DEL is refused anywhere in a reply; tab stays in the text, and line feed and carriage return end lines."""
    for code in (*range(0x00, 0x20), *range(0x7F, 0xA0)):
        lesson = parse_lesson(_LESSON.render().replace("night watch", f"night{chr(code)}watch"))
        if chr(code) in "\t\n\r":
            assert lesson is not None, hex(code)
            assert parse_lesson(lesson.render()) == lesson
        else:
            assert lesson is None, hex(code)


@pytest.mark.parametrize(
    "reply, declined",
    [
        (DECLINE_REPLY, True), ("No notes.", True), ("**NO NOTES**", True), ("", True), ("   \n", True),
        ("__NO NOTES__", True), ("_no notes_", True), ("no_notes", False),
        ("No notes on the coolant yet, but here they are.", False), (_LESSON.render(), False), (None, False),
    ],
    ids=[
        "exact", "punctuation", "bold", "empty", "blank", "underscore-bold", "underscore", "joined-by-underscore",
        "a-sentence", "a-lesson", "not-text",
    ],
)
def test_a_declining_reply_is_recognised_and_nothing_else_is(reply: object, declined: bool) -> None:
    assert is_declined(reply) is declined


_OFFERED = {"e1": "ep-a", "e2": "ep-b", "e3": "ep-c"}


@pytest.mark.parametrize(
    "cites, expected",
    [
        ("Cites: e1, e3", ("ep-a", "ep-c")),
        ("cites: E3 e1 e3", ("ep-c", "ep-a")),
        ("**Cites:** e01", ("ep-a",)),
        ("Cites: e9, e13, x1", ()),
        ("Cites: e2\nCites: e1", ("ep-b", "ep-a")),
        ("", ()),
    ],
    ids=["two", "order-and-once", "bold-and-padded", "not-offered", "two-lines", "none"],
)
def test_citations_name_only_the_episodes_offered(cites: str, expected: tuple[str, ...]) -> None:
    assert parse_citations(f"{_LESSON.render()}\n{cites}", _OFFERED) == expected


def test_a_lesson_cites_at_most_the_bounded_number_of_episodes() -> None:
    offered = {f"e{index}": f"ep-{index:03d}" for index in range(1, 21)}

    cited = parse_citations("Cites: " + ", ".join(offered), offered)

    assert cited == tuple(f"ep-{index:03d}" for index in range(1, LESSON_MAX_CITATIONS + 1))


#: The longest inheritance label S2 writes (a six-digit generation) and the longest provenance marker the Oracle tool
#: puts before an archive entry it has just retrieved (relevance at most 1.00, retrieved under a minute ago).
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:59s]"


async def test_a_whole_note_at_every_bound_reaches_a_later_crew_through_the_oracle_tool(tmp_path: Path) -> None:
    """A2 (M1-F4): the Oracle tool cuts each entry to ``_MAX_ENTRY_CHARS``. A note at every bound (the lesson at
    ``LESSON_MAX_CHARS``, the callsign, agent type and timeline at theirs) reaches a later crew whole: all four
    sections, nothing shortened, with room left for the longest label and marker."""
    names = ("OBS_BODY", "DISCUSSION_BODY", "LESSON_BODY", "RECOMMENDATION_BODY")
    bodies = tuple(f"{name} " + "x" * (LESSON_MAX_CHARS // 4 - len(name) - 1) for name in names)
    assert sum(len(body) for body in bodies) == LESSON_MAX_CHARS  # premise: at the bound
    longest = LessonLearned(*bodies)
    assert parse_lesson(longest.render()) == longest
    assert parse_lesson(LessonLearned(bodies[0] + "x", *bodies[1:]).render()) is None  # one character more
    callsign, agent_type, timeline = (
        "C" * EXIT_NOTE_CALLSIGN_MAX_CHARS, "a" * EXIT_NOTE_AGENT_TYPE_MAX_CHARS, "t" * EXIT_NOTE_TIMELINE_MAX_CHARS,
    )
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, timeline=timeline, agent_type=agent_type, callsign=callsign, lesson=longest)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        assert (await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)).created == (path,)
        oracle = OracleService(archive_store=archive)
        oracle.attach_current_timeline(_NEXT_SHIP)  # a later crew reads it
        result = await OracleQueryTool(oracle=oracle).invoke({"query": "RECOMMENDATION_BODY", "kind": "archive"})
    finally:
        await archive.close()

    assert not result.error and result.metadata["returned_count"] == 1  # premise: the real tool delivered it
    entry = result.output[result.output.index("[source:archive"):].rstrip("\n")
    marker, label = entry.splitlines()[:2]
    assert label.startswith("[Inherited from ")  # premise: S2's label comes first after the marker
    assert "[entry shortened]" not in entry
    for body in bodies:
        assert body in entry  # the Lesson and the Recommendation too, not only the Observation
    worst = len(entry) - len(marker) - len(label) + len(_WORST_MARKER) + len(_WORST_LABEL)
    assert worst <= _MAX_ENTRY_CHARS  # the longest label and marker would still leave it whole


def test_an_exit_note_has_one_path_per_timeline_and_agent_type() -> None:
    assert exit_notes_directory("Ship-DID Alpha/0001") == "exit-notes/ship-did-alpha-0001"
    assert exit_note_path("Ship-DID Alpha/0001", "data_analyst") == "exit-notes/ship-did-alpha-0001/data-analyst.md"
    for bad in ("", "  ", "///", "..", None):
        with pytest.raises(ValueError):
            exit_note_path(bad, "surgeon")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            exit_note_path(_SHIP, bad)  # type: ignore[arg-type]


# --- P1 to P3: the promotion ----------------------------------------------------------------------------------------


async def test_an_exit_note_is_promoted_with_its_own_provenance(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, cited=("ep-000", "ep-001"))
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        promoted = await promote_ship_records(records, archive, timeline_id="timeline-of-the-reset")
    finally:
        await archive.close()

    assert promoted.created == (path,)
    assert promoted.withheld == ()
    columns = (
        "timeline_id, category, title, content, author_agent_type, author_callsign, source_kind, source_ref, "
        "classification, author_did, source_episode_ids"
    )
    assert _rows(tmp_path / "archive.db", f"SELECT {columns} FROM archive") == [(
        _SHIP, "exit_note", "Exit notes of Chapel", exit_note_body("Chapel", "surgeon", _SHIP, _LESSON), "surgeon",
        "Chapel", "exit_note", path, "ship", _DID, json.dumps(["ep-000", "ep-001"]),
    )]


_BROKEN: dict[str, dict[str, Any]] = {
    "no-envelope": {"with_envelope": False},
    "wrong-version": {"envelope": {"version": 2}},
    "blank-did": {"did": "  "},
    "path-mismatch": {"path": "exit-notes/another-timeline/surgeon.md"},
    "author-mismatch": {"author": "Bones"},
    "header-missing": {"content": _LESSON.render()},
    "body-not-in-format": {"content": f"{exit_note_header('Chapel', 'surgeon', _SHIP)}\n\nA few thoughts, unsorted."},
    "too-many-citations": {"cited": tuple(f"ep-{index:03d}" for index in range(LESSON_MAX_CITATIONS + 1))},
    "duplicate-citation": {"cited": ("ep-000", "ep-000")},
    "blank-citation": {"cited": ("ep-000", " ")},
    "department": {"classification": "department"},
    # A2: what the rule checked too little (M1-F2, F5, F6, F7; M2-7).
    "bool-version": {"envelope": {"version": True}},
    "float-version": {"envelope": {"version": 1.0}},
    "newline-callsign": {"callsign": "Chapel\n## Observation"},
    "nul-agent-type": {"agent_type": "sur\x00geon"},
    "surrogate-did": {"did": "did:probos:x:\ud800"},
    "long-callsign": {"callsign": "C" * (EXIT_NOTE_CALLSIGN_MAX_CHARS + 1)},
    "preamble": {
        "content": f"{exit_note_header('Chapel', 'surgeon', _SHIP)}\n\nA preamble the parser drops.\n\n{_LESSON.render()}",
    },
    "standalone-cites": {"content": f"{exit_note_body('Chapel', 'surgeon', _SHIP, _LESSON)}\nCites: e1"},
    # A4: an episode id the rule refuses (R2-F4's missing case), a lookalike heading (R2-F2), a control (R2-F5).
    "long-citation": {"cited": ("ep-000", "e" * (EXIT_NOTE_EPISODE_ID_MAX_CHARS + 1))},
    "newline-citation": {"cited": ("ep-000", "ep\n001")},
    "lookalike-heading": {
        "content": exit_note_body("Chapel", "surgeon", _SHIP, _LESSON).replace("## Lesson", "## Le\u017fson"),
    },
    "control-in-body": {
        "content": exit_note_body("Chapel", "surgeon", _SHIP, _LESSON).replace("cleared", "\x1b[2Jcleared"),
    },
}


@pytest.mark.parametrize("case", sorted(_BROKEN))
async def test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, **_BROKEN[case])

    plan = await plan_promotion(records, timeline_id=_SHIP)  # never raises: a bad note is withheld

    assert plan.records == ()
    assert plan.withheld == (path,)
    assert await exit_note_citations(records, None) == {}


#: A4 (R2-F3): text YAML must quote or escape, the frontmatter delimiter, and characters outside ASCII.
_YAML_HARD = (
    "---", "--- x", "-- -", "- x", "? x", ": x", "x: y", " #x", "#x", "'x", '"x', "\\x", "{x}", "[x]", "&x", "*x",
    "!x", "%x", "@x", "`x", "|x", ">x", "~", "null", "yes", "No", "1", "1.0", "0x1F", "2026-10-26", " x", "x ",
    "x  y", "...", "\u00e9", "\U0001f680", "\ufeff", "\u00a0", "\u0085", "\u2028",
)


@pytest.mark.parametrize("field", ["callsign", "agent_type", "did", "cited"])
async def test_every_provenance_value_the_rule_admits_comes_back_whole_from_ship_s_records(
    tmp_path: Path, field: str,
) -> None:
    """A4 (R2-F3): Ship's Records cuts a document's frontmatter at the first two ``---`` it finds, wherever they stand
    (register R25), so a callsign such as ``normal---value`` came back as ``normal``: the stand-down reported the
    note written and the promotion withheld it. The rule now refuses a value holding ``---``. Each value here (YAML's
    quoting cases, and for the callsign, which the store writes three times, every code point to U+017F) is either
    refused by the rule and withheld, or admitted, stored, read back whole and archived."""
    records = _records(_data_dir(tmp_path))
    bound = {
        "callsign": EXIT_NOTE_CALLSIGN_MAX_CHARS, "agent_type": EXIT_NOTE_AGENT_TYPE_MAX_CHARS,
        "did": EXIT_NOTE_DID_MAX_CHARS, "cited": EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    }[field]
    values = [f"Ch{text}pel" for text in _YAML_HARD] + [f"{text}Chapel" for text in _YAML_HARD]
    if field == "callsign":
        values += [f"Ch{chr(code)}pel" for code in range(0x180)]
    admitted_seen = refused_seen = 0
    for value in values:
        note = {"cited": ("ep-000", value)} if field == "cited" else {field: value}
        path = await _write_note(records, **note)
        plan = await plan_promotion(records, timeline_id=_SHIP)
        (records.repo_path / path).unlink()
        if is_exit_note_text(value, bound):
            (record,) = plan.records
            stored = {
                "callsign": record.author_callsign, "agent_type": record.author_agent_type, "did": record.author_did,
                "cited": record.source_episode_ids[-1],
            }[field]
            assert stored == value, repr(value)
            admitted_seen += 1
        else:
            assert plan.records == (), repr(value)
            refused_seen += 1
    assert admitted_seen and refused_seen  # premise: both kinds were exercised


def test_a_note_the_rule_refuses_is_withheld_and_the_real_reset_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4 (R2-F2): a stored note whose heading is spelled with a lookalike letter raised ``KeyError`` through the
    rule, the plan and the real ``probos reset``, which exited 1 with nothing wiped. A note that breaks the rule is
    withheld, and the reset runs."""
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    lookalike = exit_note_body("Chapel", "surgeon", _SHIP, _LESSON).replace("## Discussion", "## D\u0131scussion")
    path = asyncio.run(_write_note(_records(data_dir), content=lookalike))

    assert _reset(monkeypatch, config, data_dir) == 0
    assert (path,) not in _rows(tmp_path / "archive.db", "SELECT source_ref FROM archive")


_HUGE = "0x" + "1" * 4000  # A5: a YAML integer whose decimal form is longer than Python's integer-string limit


@pytest.mark.parametrize(
    "source, field",
    [
        ("exit-note", "status"), ("exit-note", "created"), ("exit-note", "updated"), ("finding", "author"),
        ("finding", "status"), ("finding", "department"), ("finding", "created"), ("finding", "updated"),
        ("finding", "topic"),
    ],
)
async def test_a_stored_value_that_cannot_be_shown_as_text_never_stops_the_promotion(
    tmp_path: Path, source: str, field: str,
) -> None:
    """A5 (round 3 R3-M1-2): ``str()`` raises ``ValueError`` for an integer longer than Python's integer-string limit
    (YAML reads ``0x...`` into one), so one stored value stopped the plan and the whole reset. Such a value is archived
    as no value, as a missing one is, and a title falls back to the file name; S1's sources had the same conversions."""
    records = _records(_data_dir(tmp_path))
    if source == "exit-note":
        path = await _write_note(records)
    else:
        path = "notebooks/bones/finding.md"
        await records.write_entry(
            author="Bones", path=path, content="A finding.", message="test: a finding", classification="ship",
            department="medical", topic="Coolant drift", extra_frontmatter={"claim_id": "claim-0001"},
        )
    stored = records.repo_path / path
    raw = stored.read_text(encoding="utf-8")
    assert re.search(rf"(?m)^{field}:", raw)  # premise: the store wrote the field
    stored.write_text(re.sub(rf"(?m)^{field}:.*$", f"{field}: {_HUGE}", raw), encoding="utf-8")

    plan = await plan_promotion(records, timeline_id=_SHIP)

    (record,) = plan.records
    shown = {
        "author": record.author_callsign, "topic": record.title, "status": record.metadata["status"],
        "department": record.metadata.get("department"), "created": record.metadata["record_created"],
        "updated": record.metadata["record_updated"],
    }[field]
    assert shown == ("finding" if field == "topic" else "")


def test_a_note_holding_a_value_that_cannot_be_shown_as_text_is_archived_by_the_real_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A5 (round 3 R3-M1-2): the reviewer's case through the real ``probos reset``, which exited 1 with nothing
    wiped. The note is valid, so the reset archives it, with no status."""
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    path = asyncio.run(_write_note(_records(data_dir)))
    stored = _records(data_dir).repo_path / path
    raw = stored.read_text(encoding="utf-8")
    stored.write_text(re.sub(r"(?m)^status:.*$", f"status: {_HUGE}", raw), encoding="utf-8")

    assert _reset(monkeypatch, config, data_dir) == 0
    assert (path,) in _rows(tmp_path / "archive.db", "SELECT source_ref FROM archive")


async def test_an_exit_note_is_archived_once_whichever_reset_promotes_it(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        first = await promote_ship_records(records, archive, timeline_id=_SHIP)
        again = await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)  # tier 2 keeps Ship's Records
    finally:
        await archive.close()

    assert first.created == (path,)
    assert (again.created, again.present) == ((), (path,))
    assert _rows(tmp_path / "archive.db", "SELECT COUNT(*), MIN(timeline_id) FROM archive") == [(1, _SHIP)]


# --- C1 to C4: the erasure's read, and the Captain's review ---------------------------------------------------------


@pytest.mark.parametrize("state", ["new", "vetoed", "erased", "present", "uncited", "no-archive"])
async def test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it(
    tmp_path: Path, state: str,
) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, cited=() if state == "uncited" else ("ep-000",))
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        record = (await plan_promotion(records, timeline_id=_SHIP)).records[0]
        if state == "vetoed":
            outcome = await archive.veto_source(SourceKind.EXIT_NOTE, path, "not canon", timeline_id=_SHIP)
            assert outcome is VetoOutcome.RECORDED
        elif state in ("erased", "present"):
            assert await archive.promote_entry(record) is PromotionOutcome.CREATED
            if state == "erased":
                entry_id = _rows(tmp_path / "archive.db", "SELECT id FROM archive")[0][0]
                assert await archive.erase_entry(entry_id, "the Captain forgets it") is True
        cited = await exit_note_citations(records, None if state == "no-archive" else archive)
    finally:
        await archive.close()

    expected = {"ep-000": (path,)} if state in ("new", "no-archive") else {}
    assert cited == expected


async def test_a_veto_between_the_citation_read_and_the_promotion_decides_both(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        before = await exit_note_citations(records, archive)
        assert await archive.veto_source(SourceKind.EXIT_NOTE, path, "not canon", timeline_id=_SHIP) is VetoOutcome.RECORDED
        after = await exit_note_citations(records, archive)
        promoted = await promote_ship_records(records, archive, timeline_id=_SHIP)
    finally:
        await archive.close()

    assert before == {"ep-000": (path,)}
    assert after == {}
    assert (promoted.created, promoted.vetoed) == ((), (path,))


class _Unlistable(RecordsStore):
    async def list_entries(self, directory: str = "", **filters: Any) -> list[dict]:
        raise OSError("Ship's Records cannot be listed")


async def test_the_citation_read_raises_when_ship_s_records_cannot_be_listed(tmp_path: Path) -> None:
    records = _Unlistable(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))

    with pytest.raises(OSError):
        await exit_note_citations(records, None)


async def test_ship_s_records_without_exit_notes_cite_nothing(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))  # no exit-notes/ directory at all

    assert await exit_note_citations(records, None) == {}


@pytest.mark.parametrize("case", ["not-a-mapping", "not-utf-8"])
async def test_a_document_the_promotion_skips_is_never_read_as_a_citing_note(tmp_path: Path, case: str) -> None:
    """A1: frontmatter that is not a mapping. ``plan_promotion`` skips the document unread, so it can never be
    archived; the citation read skips it too, instead of raising in ``read_entry`` and stopping every erasure. A2:
    bytes that are not UTF-8 are a property of the file, not of the moment; the promotion never sees the document, and
    the strict read skips it too rather than refusing every erasure while it sits in ``exit-notes/``."""
    records = _records(_data_dir(tmp_path))
    stray = records.repo_path / exit_note_path(_SHIP, "surgeon")
    stray.parent.mkdir(parents=True)
    if case == "not-a-mapping":
        stray.write_text("---\nnot a mapping\n---\nCites: ep-000\n", encoding="utf-8")
    else:
        stray.write_bytes(b"---\nauthor: Chapel\n---\n\xff\xfe Cites: ep-000\n")

    plan = await plan_promotion(records, timeline_id=_SHIP)

    assert (plan.records, plan.withheld) == ((), ())  # premise: the promotion skips it
    assert await exit_note_citations(records, None) == {}


@pytest.mark.parametrize("fault", ["injected", "native"])
async def test_a_note_the_listing_cannot_read_now_is_never_read_as_no_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """A2 (M1-F1, M3-F1): a valid citing note the OS refuses to read at this moment. The real listing meets the
    failure inside its own loop; the citation read raises instead of answering that nothing cites the episode, while
    every other reader of Ship's Records keeps skipping the file as before. Readable again, the note counts."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    note = records.repo_path / path
    with contextlib.ExitStack() as stack:
        if fault == "injected":
            _deny_reading(monkeypatch, note)
        else:
            stack.enter_context(_unreadable(note))
        assert await records.list_entries(EXIT_NOTES_DIR) == []  # premise: the default listing skips it, as before
        with pytest.raises(OSError):
            await exit_note_citations(records, None)
        monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


@pytest.mark.parametrize(
    "fault", ["injected-root", "injected-timeline", "injected-entry-type", "native-root", "native-timeline"],
)
async def test_a_note_directory_the_listing_cannot_list_now_is_never_read_as_no_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """A4 (R2-F1, M3-1): the OS refuses to list ``exit-notes/`` or the timeline directory holding a valid citing note.
    ``Path.rglob`` passes over such a directory, so the strict citation read answered that nothing cites the episode
    and the AD-754 erasure went ahead. The strict listing now raises, and the citation read with it, while the default
    listing never raises, as before. Listable again, the note counts. ``[native-*]``: a share-nothing handle on
    Windows, mode 000 on POSIX (skips only where the account lists it anyway). A5 (R3-M1-1): ``[injected-entry-type]``,
    the OS cannot report the timeline directory's type; ``os.walk`` took it for a file and the read answered ``{}``."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    timeline_directory = (records.repo_path / path).parent
    denied = timeline_directory.parent if fault.endswith("-root") else timeline_directory
    with contextlib.ExitStack() as stack:
        if fault == "injected-entry-type":
            _deny_entry_type(monkeypatch, timeline_directory)
        elif fault.startswith("injected"):
            _deny_listing(monkeypatch, denied)
        else:
            stack.enter_context(_unreadable(denied))
        default = await records.list_entries(EXIT_NOTES_DIR)  # never raises: every other reader is unchanged
        if fault.startswith("native"):
            assert default == []  # premise: the OS itself refused to list the directory
        with pytest.raises(OSError):
            await records.list_entries(EXIT_NOTES_DIR, strict=True)
        with pytest.raises(OSError):
            await exit_note_citations(records, None)
        monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


@pytest.mark.parametrize(
    "directory", ["", EXIT_NOTES_DIR, f"{EXIT_NOTES_DIR}/absent"], ids=["all", "exit-notes", "absent"],
)
async def test_the_strict_listing_lists_exactly_what_the_default_listing_lists(tmp_path: Path, directory: str) -> None:
    """A4, A5: the strict listing lists what the default listing lists, in the same order: nested directories, a
    directory named ``*.md`` (A5: never returned by the walk; the default reads it as no file), another suffix, the
    suffix's case as the platform matches it, ``_archived/``, and a directory that does not exist."""
    records = _records(_data_dir(tmp_path))
    await _write_note(records)
    for relative in (
        "exit-notes/a/b/deep.md", "exit-notes/UPPER.MD", "exit-notes/plain.txt", "_archived/old.md", "top.md",
    ):
        (records.repo_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (records.repo_path / relative).write_text("---\nauthor: Bones\n---\n\nA record.\n", encoding="utf-8")
    (records.repo_path / "exit-notes" / "folder.md").mkdir()

    default = await records.list_entries(directory)

    assert await records.list_entries(directory, strict=True) == default
    assert len(default) >= (0 if directory.endswith("absent") else 2)  # premise: something to list


@pytest.mark.parametrize("kind", sorted(_WALK_FAULTS))
def test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing(tmp_path: Path, kind: str) -> None:
    """A5 (round 3 R3-M1-1): a trace-and-fault matrix over 7.3a's table, not one case per round. A clean walk over a
    real tree records every filesystem operation it makes (each ``os.scandir``, each listing step, the last one
    included, each ``is_dir``); the trace allows nothing else, so an operation added without a row fails here. Then
    each recorded operation fails once with ``kind``: the walk raises that error, except a missing root
    (``FileNotFoundError`` or ``NotADirectoryError`` at the root's open), which lists nothing. Every cell first asserts
    that its fault fired at the operation the clean walk made there."""
    root = tmp_path / "exit-notes"
    _walk_tree(root)
    clean = _Trace()
    found = sorted(_traced_walk(root, clean))
    assert found == sorted(path for path in root.rglob("*.md") if path.is_file())  # rglob's files, on a sound tree
    assert set(clean.operations) == {"open-root", "open-subdirectory", "next", "is_dir"}  # one row each, no other
    for fail_at, operation in enumerate(clean.operations, start=1):
        trace = _Trace(fail_at, _WALK_FAULTS[kind])
        try:
            outcome: Any = sorted(_traced_walk(root, trace))
        except OSError as exc:
            outcome = type(exc)
        assert trace.fired == operation, (fail_at, operation)  # premise: this cell's fault fired where it was aimed
        missing_root = operation == "open-root" and kind in ("absent", "not-a-directory")
        assert outcome == ([] if missing_root else type(_WALK_FAULTS[kind]("cell"))), (fail_at, operation)


@pytest.mark.parametrize("stat", ["stat-ok", "stat-ebadf"])
@pytest.mark.parametrize("kind", ["permission", "io", "absent", "not-a-directory"])
async def test_a_listed_note_the_strict_read_cannot_read_is_never_read_as_no_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, stat: str,
) -> None:
    """A5 (7.3a's table, O5): a listed note whose read fails, with any error, raises from the strict listing and the
    citation read; the default listing still skips it; readable again, it counts. ``[*-stat-ebadf]``: A2's
    ``Path.is_file()`` then answered "not there" (``pathlib`` reads EBADF, ENOENT, ENOTDIR, ELOOP and three Windows
    errors so), and the note was skipped as absent. The strict read no longer asks: the walk's listing decides."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    note = records.repo_path / path
    _deny_reading(monkeypatch, note, error=_WALK_FAULTS[kind](str(note)))
    if stat == "stat-ebadf":
        _deny_stat(monkeypatch, note, OSError(errno.EBADF, "bad file descriptor", str(note)))
    assert await records.list_entries(EXIT_NOTES_DIR) == []  # premise: the default listing skips it, as before
    with pytest.raises(OSError):
        await records.list_entries(EXIT_NOTES_DIR, strict=True)
    with pytest.raises(OSError):
        await exit_note_citations(records, None)
    monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


@pytest.mark.parametrize("error", ["ebadf", "enoent", "eacces"])
async def test_a_listed_note_the_citation_read_cannot_find_again_is_never_read_as_no_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str,
) -> None:
    """A5 (7.3a's table, O6): ``exit_note_citations`` reads each listed note again through ``read_entry``, whose
    ``Path.exists`` answers False for EBADF and ENOENT (and on Windows "the device is not ready"), so a note listed and
    read a moment before came back None and cited nothing. A ship-wide note the strict listing returned and
    ``read_entry`` cannot find now raises. ``[eacces]``: ``exists`` raises itself (the control)."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    note = records.repo_path / path
    code = {"ebadf": errno.EBADF, "enoent": errno.ENOENT, "eacces": errno.EACCES}[error]
    _deny_stat(monkeypatch, note, OSError(code, os.strerror(code), str(note)))
    listed = await records.list_entries(EXIT_NOTES_DIR, strict=True)
    assert [entry["path"] for entry in listed] == [path]  # premise: the strict listing listed and read it
    with pytest.raises(OSError):
        await exit_note_citations(records, None)
    monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


async def test_the_captain_s_review_lists_an_exit_note_as_a_source_to_be_promoted(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        review = await review_promotion(records, archive, timeline_id=_SHIP)
    finally:
        await archive.close()

    assert [(pending.record.source_ref, pending.state.outcome) for pending in review.sources] == [
        (path, PromotionOutcome.CREATED),
    ]
    assert review.sources[0].record.source_kind is SourceKind.EXIT_NOTE
```

### 7.6 New file: `src/probos/stand_down.py` (M2)

```python
"""AD-1341 S4 (#1569): the stand-down, each crew agent's one bounded turn to leave exit notes before a reset.

``probos reset`` runs with the vessel stopped (S1's AD-816 pidfile), so no agent can think inside it (#1569, the
Architect's premise P1). The stand-down is the live step before it. The Captain types ``/stand-down`` at the vessel's
console, and every crew agent is sent one Captain's message: a ``direct_message`` intent through the intent bus, as a
1:1 message is, that asks for exit notes in the lessons format (``probos.knowledge.lessons``) and shows the agent its
own most recent episodes by handle. Writing is optional. The message is a bounded turn (``BOUNDED_TURN_PARAM``, A2): the
agent answers it on its single-pass path, without its tool-calling loop, so nothing the turn starts outlives it.

No agent can hold a reset. Each turn is bounded by ``STAND_DOWN_TURN_SECONDS``, the whole stand-down by
``STAND_DOWN_WINDOW_SECONDS``, and at most ``STAND_DOWN_CONCURRENCY`` turns run at once. A turn that runs out of time
is cancelled; a turn whose reply comes late, fails or is never reached writes nothing, and no write begins once the
window has closed. Nothing the stand-down published is ever removed (A4): a write that fails or is cut off after
publishing is reported with its path. ``probos reset`` neither waits for a stand-down nor needs one.

A note is a Ship's Records document at ``exit_note_path(timeline, agent_type)``, written with the author's callsign,
agent type and DID, the ids of the episodes it cites (only episodes the agent was shown), ``ship`` classification and
status ``submitted``. A note already written in this timeline is never overwritten, so a second stand-down asks only
the agents without one. The reset's promotion archives each note before anything is wiped
(``probos.knowledge.archive_promotion``); the Captain reviews the notes with ``probos archive pending`` and may veto any
of them first. This module never writes the Ship's Archive and never copies an episode's text into a note.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from probos.dm_reply import DmReply
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_TIMELINE_MAX_CHARS,
    EXIT_NOTE_VERSION,
    LESSON_MAX_CHARS,
    LESSON_MAX_CITATIONS,
    exit_note_body,
    exit_note_lesson,
    exit_note_path,
    exit_note_provenance_ok,
    exit_notes_directory,
    is_declined,
    is_exit_note_text,
    parse_citations,
    parse_lesson,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
    from pathlib import Path

    from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

#: AD-1341 S4 (D5): the longest one agent's turn may take.
STAND_DOWN_TURN_SECONDS: Final = 180.0
#: AD-1341 S4 (D5): the longest the whole stand-down may take.
STAND_DOWN_WINDOW_SECONDS: Final = 900.0
#: AD-1341 S4 (D5): the most turns that run at once, inside AD-636's six concurrent model calls.
STAND_DOWN_CONCURRENCY: Final = 2
#: AD-1341 S4 (D4): the most recent episodes an agent is shown, each by handle, date and opening characters.
STAND_DOWN_EPISODES: Final = LESSON_MAX_CITATIONS
#: A2 (M2-8): an excerpt's bound in bytes once JSON-escaped (the transport escapes every character outside ASCII), so
#: in characters too; the Captain's message stays inside the 4 KiB standard for inline ``IntentMessage.params`` (S7c).
EPISODE_EXCERPT_CHARS: Final = 160
#: A2 (M2-1): the ``direct_message`` param that makes the turn a bounded one. ``CognitiveAgent`` answers it on the
#: single-pass path, so no tool-calling loop runs and nothing is promoted into a background work item past the turn.
BOUNDED_TURN_PARAM: Final = "bounded_turn"


@dataclass(frozen=True)
class CrewMember:
    """One crew agent as the stand-down addresses it. ``did`` and ``callsign`` are empty when no identity resolves."""

    agent_id: str
    agent_type: str
    sovereign_id: str = ""
    did: str = ""
    callsign: str = ""


class TurnOutcome(StrEnum):
    """What one agent's stand-down turn came to.

    WRITTEN wrote its note. The stand-down never removes a document (A4). A FAILED or TIMED_OUT turn that carries a
    path is a write that did not complete and may have left a document there: it published before it failed or was
    cut off, or whether it did could not be checked (A5, round 3 M2-2). The report names the path, the console counts
    such turns apart from WRITTEN, and the Captain's review lists any note the next promotion would archive there. A
    FAILED turn without a path wrote nothing, a billet that could not be checked included (A5). Every other outcome
    left nothing at its path, or found a note there already (ALREADY_WRITTEN, DUPLICATE).
    """

    WRITTEN = "written"
    DECLINED = "declined"
    NOT_IN_FORMAT = "not_in_format"
    NO_REPLY = "no_reply"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_REACHED = "not_reached"
    ALREADY_WRITTEN = "already_written"
    NO_IDENTITY = "no_identity"
    DUPLICATE = "duplicate"  # A2 (M2-3): this billet's path is another crew agent's turn in this stand-down


@dataclass(frozen=True)
class TurnResult:
    """One agent's turn: who, what it came to, and the note's records path when there is one."""

    agent_type: str
    callsign: str
    outcome: TurnOutcome
    path: str = ""


@dataclass(frozen=True)
class StandDownReport:
    """One stand-down: the timeline its notes belong to, and each crew agent's turn in crew order."""

    timeline_id: str
    turns: tuple[TurnResult, ...]

    def count(self, outcome: TurnOutcome) -> int:
        """How many turns came to ``outcome``."""
        return sum(1 for turn in self.turns if turn.outcome is outcome)


class StandDownRefused(Exception):
    """No stand-down can run on this vessel now. Nobody was asked and nothing was written."""


Ask = Callable[[CrewMember, str], Awaitable[str | None]]
Recall = Callable[[CrewMember], Awaitable[Sequence[Any]]]


def _turn_result(member: CrewMember, outcome: TurnOutcome, path: str = "") -> TurnResult:
    return TurnResult(member.agent_type, member.callsign, outcome, path)


def _present(path: Path) -> bool | None:
    """A5 (7.3a's table, O7): True when something is at ``path``, False when nothing is, None when that cannot be told.

    ``Path.exists`` answers False for errors ``pathlib`` reads as "not there" (EBADF and ELOOP, and on Windows "the
    device is not ready" among others), so a note there could be taken for none and written over, or left out of the
    report. Only "not found", or a parent that is no directory, is absent. ``lstat``: whatever is at the billet's path
    is there, and a link is never followed.
    """
    try:
        path.lstat()
    except (FileNotFoundError, NotADirectoryError):  # A5: nothing is there
        return False
    except OSError:
        return None
    return True


def _offer(episodes: Sequence[Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    """The handles an agent may cite (``e1`` -> an episode id) and the lines that show them (D4, D9).

    The agent's own most recent episodes, at most ``STAND_DOWN_EPISODES``, each by handle, date and opening words of
    at most ``EPISODE_EXCERPT_CHARS`` bytes once JSON-escaped. An episode seen twice, or whose id the promotion's rule
    refuses (``is_exit_note_text``: blank, over 128 characters, not one line, or holding ``---``; A4), is skipped.
    """
    offered: dict[str, str] = {}
    shown: list[str] = []
    for episode in episodes:
        if len(offered) >= STAND_DOWN_EPISODES:
            break
        episode_id = getattr(episode, "id", None)
        if not is_exit_note_text(episode_id, EXIT_NOTE_EPISODE_ID_MAX_CHARS) or episode_id in offered.values():
            continue  # A4 (R2-F4): an id the promotion's rule refuses is never offered
        handle = f"e{len(offered) + 1}"
        offered[handle] = episode_id
        day, excerpt = _day(getattr(episode, "timestamp", 0.0)), _excerpt(getattr(episode, "user_input", ""))
        shown.append(f"{handle} {day}: {excerpt}")
    return offered, tuple(shown)


def _day(stamp: object) -> str:
    """An episode's date, or ``undated`` for a timestamp that names none (missing, not positive, NaN, out of range)."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not stamp > 0:
        return "undated"
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(stamp))
    except (OverflowError, OSError, ValueError):  # A2 (M2-6): inf, or out of range; the turn still runs
        return "undated"


def _excerpt(text: object) -> str:
    """An episode's opening words: at most ``EPISODE_EXCERPT_CHARS`` bytes once JSON-escaped (A2, M2-8)."""
    kept: list[str] = []
    cost = 0
    for char in " ".join(str(text or "").split()):
        if "\ud800" <= char <= "\udfff":
            continue  # a lone surrogate is no UTF-8: dropped, never sent
        cost += len(json.dumps(char)) - 2
        if cost > EPISODE_EXCERPT_CHARS:
            break
        kept.append(char)
    return "".join(kept)


def exit_notes_prompt(callsign: str, shown: Sequence[str]) -> str:
    """AD-1341 S4 (D4): the Captain's message for one agent's turn: why, what, that it is optional, where it goes."""
    episodes = "\n".join(shown) if shown else "(none could be read)"
    return (
        f"Captain to {callsign}: the crew is standing down before a reset. Your successor in this billet will not share "
        "your memories. This is your one turn to leave them exit notes: what you learned, what you would do "
        "differently, and what remains open.\n\n"
        f"Writing is optional. To decline, reply exactly {DECLINE_REPLY} and nothing is recorded.\n\n"
        "If you write, reply in exactly this form, from your own experience, the four sections together at most "
        f"{LESSON_MAX_CHARS} characters:\n"
        "## Observation\n(what happened)\n"
        "## Discussion\n(why it happened and why it mattered)\n"
        "## Lesson\n(the general learning)\n"
        "## Recommendation\n(what your successor should do differently, and what remains open)\n"
        "Cites: (optional) the handles of the episodes below that your observation rests on, for example e1, e3\n\n"
        "Your notes are kept in Ship's Records under your callsign and DID. The Captain may review them and veto them; "
        "otherwise they are archived in the Ship's Archive at the reset, where every later crew can read them, "
        "labelled as inherited from this crew. Write nothing you would not share with the whole ship. Summarise in "
        "your own words; do not quote your memories. Reply with the notes alone, without using tools.\n\n"
        f"Your most recent episodes (handle, date, opening words):\n{episodes}"
    )


async def run_stand_down(
    crew: Sequence[CrewMember],
    *,
    ask: Ask,
    recall: Recall,
    records: RecordsStore,
    timeline_id: str,
    turn_seconds: float = STAND_DOWN_TURN_SECONDS,
    window_seconds: float = STAND_DOWN_WINDOW_SECONDS,
    concurrency: int = STAND_DOWN_CONCURRENCY,
    clock: Callable[[], float] = time.monotonic,
) -> StandDownReport:
    """Give each crew member one bounded turn to leave exit notes, and write each note it leaves (D3 to D11).

    ``ask`` delivers the prompt and returns the reply (None for no reply); ``recall`` returns the member's most recent
    episodes. Returns by ``window_seconds`` after it starts, plus the cancellation of what is still running then: the
    window includes the first read of Ship's Records and every write (A2, M2-2). Each member's turn has one deadline,
    ``turn_seconds`` after it begins and never past the window, that its recall and its ask both spend and that its
    reply must meet (A2, M2-5). One turn per billet: a second crew agent of an agent type, or a member listed twice, is
    ``DUPLICATE`` and is not asked (A2, M2-3). No write begins once the window has closed, and nothing the stand-down
    published is removed: a write that fails or is cut off after publishing is reported with its path (A4).

    Raises ``StandDownRefused`` when the timeline is missing, cannot stand in a note or name a records path, or when
    Ship's Records cannot be read in time, a first read that returns after the window has closed included (A5; nobody
    is asked), and ``ValueError`` for a bound that is not positive.
    Nothing that happens in a member's turn raises, and no turn outlives the call.
    """
    if type(timeline_id) is not str or not timeline_id.strip():
        raise StandDownRefused("This vessel has no instance id, so its exit notes could not be attributed to a timeline.")
    if concurrency < 1 or turn_seconds <= 0 or window_seconds <= 0:
        raise ValueError("AD-1341 S4: a stand-down's bounds must be positive")
    if not is_exit_note_text(timeline_id, EXIT_NOTE_TIMELINE_MAX_CHARS):
        raise StandDownRefused(
            f"The instance id cannot stand in an exit note (one line, at most {EXIT_NOTE_TIMELINE_MAX_CHARS} characters)."
        )
    try:
        directory = exit_notes_directory(timeline_id)
    except ValueError as exc:
        raise StandDownRefused(f"The instance id cannot name a records path: {exc}") from exc
    deadline = clock() + window_seconds  # A2 (M2-2): the window starts before Ship's Records is first read
    try:
        listed = await asyncio.wait_for(records.list_entries(directory, strict=True), timeout=window_seconds)
    except Exception as exc:  # the window closed, or a note file could not be read: which notes exist is unknown
        logger.warning(
            "AD-1341 S4: Ship's Records could not be read for the stand-down; nobody is asked", exc_info=True,
        )
        raise StandDownRefused(
            "Ship's Records could not be read in time, so nobody was asked: a note already written could be replaced."
        ) from exc
    if clock() >= deadline:  # A5 (round 3 M2-3): the first read returned after the window closed
        # wait_for cannot cut off a read that never yields (synchronous Ship's Records I/O, register R22), so the
        # window is checked again before any turn task exists, and none begins after it.
        logger.warning("AD-1341 S4: reading Ship's Records took the whole stand-down window; nobody is asked")
        raise StandDownRefused("Reading Ship's Records took the whole stand-down window, so nobody was asked.")
    existing = {entry["path"] for entry in listed}
    claimed_paths: set[str] = set()  # A2 (M2-3): the billets a turn has taken in this stand-down
    seen_agents: set[str] = set()
    gate = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()  # one Ship's Records write at a time: the repository has one git index

    def _left_at(path: str) -> str:
        """A4: ``path`` when a document is there now, so the report names it. Unknown counts as there (A5: through
        ``_present``, which reads what ``Path.exists`` calls "not there" as unknown)."""
        return "" if _present(records.repo_path / path) is False else path

    async def _write(member: CrewMember, path: str, body: str, envelope: dict[str, Any]) -> TurnResult:
        """Write one note: begun inside the window, never over a document its check found or could not rule out, and
        reported as it is left (A2, A4, A5; a writer outside ProbOS saving at the path in the same instant: R28).

        The check for a note written since the stand-down began has no await, and its time is charged to the window
        before a write may begin (A4, round 2 M2-2). The stand-down never removes a document (A4): a write that fails,
        or that the window cuts off, may already have published its note (``write_entry`` writes the file before it
        awaits git), so the report names the path and the Captain's review lists it. A write that returns after the
        window (synchronous Ship's Records I/O, register R22) left its note: WRITTEN.
        """
        async with write_lock:
            present = _present(records.repo_path / path)  # A5: what Path.exists reads as "not there" is unknown here
            if present:  # A2 (M2-3), A4: a note written since the stand-down began; no await
                return _turn_result(member, TurnOutcome.ALREADY_WRITTEN, path)
            if present is None:  # A5: whether a note is there cannot be told now, so nothing is written over it
                logger.warning(
                    "AD-1341 S4: whether %s's exit note is already written cannot be checked; nothing is written",
                    member.callsign,
                )
                return _turn_result(member, TurnOutcome.FAILED)
            remaining = deadline - clock()  # A4: after the check, so its time is charged to the window
            if remaining <= 0:  # A2 (M2-2): the window closed while this turn waited for the write lock
                return _turn_result(member, TurnOutcome.TIMED_OUT)
            written = records.write_entry(
                author=member.callsign,
                path=path,
                content=body,
                message=f"AD-1341 S4: exit notes of {member.callsign}",
                classification="ship",  # AD-1341 S4 (D8): for the next crew, so ship-wide; C1 admits it to the archive
                status=EXIT_NOTE_STATUS,
                topic=f"Exit notes of {member.callsign}",
                tags=["exit-notes", "ad-1341"],
                extra_frontmatter={EXIT_NOTE_KEY: envelope},
            )
            try:
                await asyncio.wait_for(written, timeout=remaining)  # A2 (M2-2): the window cuts off an awaiting write
            except Exception as exc:  # log-and-degrade: TimeoutError included; the other notes are still written
                outcome = TurnOutcome.TIMED_OUT if isinstance(exc, TimeoutError) else TurnOutcome.FAILED
                logger.warning(
                    "AD-1341 S4: %s's exit note write did not complete; what it published stays and is reported",
                    member.callsign, exc_info=True,
                )
                return _turn_result(member, outcome, _left_at(path))  # A4: never removed; the report names it
        return _turn_result(member, TurnOutcome.WRITTEN, path)

    async def _ask_and_write(member: CrewMember, path: str) -> TurnResult:
        turn_deadline = min(clock() + turn_seconds, deadline)  # A2 (M2-5): one deadline for the whole turn
        try:
            episodes = await asyncio.wait_for(recall(member), timeout=max(0.001, turn_deadline - clock()))
        except Exception:  # log-and-degrade: the turn offers no episodes, so its note cites none
            logger.warning(
                "AD-1341 S4: %s's recent episodes could not be read; its turn offers none", member.callsign,
                exc_info=True,
            )
            episodes = ()
        offered, shown = _offer(episodes)
        remaining = turn_deadline - clock()  # A2 (M2-5): what the recall spent is spent
        if remaining <= 0:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        prompt = exit_notes_prompt(member.callsign, shown)
        try:
            reply = await asyncio.wait_for(ask(member, prompt), timeout=remaining)
        except TimeoutError:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        except Exception:  # log-and-degrade: one agent's failed turn never stops the others, or the reset
            logger.warning(
                "AD-1341 S4: %s's exit-notes turn failed; nothing is written", member.callsign, exc_info=True,
            )
            return _turn_result(member, TurnOutcome.FAILED)
        if clock() > turn_deadline:  # a reply after the turn's deadline (never past the window) writes nothing
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        if reply is None:
            return _turn_result(member, TurnOutcome.NO_REPLY)
        if is_declined(reply):
            return _turn_result(member, TurnOutcome.DECLINED)
        lesson = parse_lesson(reply)
        if lesson is None:
            return _turn_result(member, TurnOutcome.NOT_IN_FORMAT)
        body = exit_note_body(member.callsign, member.agent_type, timeline_id, lesson)
        if exit_note_lesson(member.callsign, member.agent_type, timeline_id, body) != lesson:
            logger.error(
                "AD-1341 S4: %s's exit note would not pass the promotion's rule; nothing is written", member.callsign,
            )
            return _turn_result(member, TurnOutcome.FAILED)  # A2 (M2-7): the promotion's own rule, before the write
        cited = parse_citations(reply, offered)
        envelope = {
            "version": EXIT_NOTE_VERSION,
            "timeline_id": timeline_id,
            "callsign": member.callsign,
            "agent_type": member.agent_type,
            "author_did": member.did,
            "source_episode_ids": list(cited),
        }
        return await _write(member, path, body, envelope)

    async def _claimed_turn(member: CrewMember) -> TurnResult:
        if not exit_note_provenance_ok(timeline_id, member.callsign, member.agent_type, member.did):
            return _turn_result(member, TurnOutcome.NO_IDENTITY)  # A2 (M2-7): no identity the note could carry
        try:
            path = exit_note_path(timeline_id, member.agent_type)
        except ValueError:
            return _turn_result(member, TurnOutcome.NO_IDENTITY)
        if path in existing:
            return _turn_result(member, TurnOutcome.ALREADY_WRITTEN, path)
        if path in claimed_paths or member.agent_id in seen_agents:  # A2 (M2-3): one turn per billet, and per agent
            return _turn_result(member, TurnOutcome.DUPLICATE, path)
        claimed_paths.add(path)  # no await since the check above: the claim cannot race
        seen_agents.add(member.agent_id)
        async with gate:
            if clock() >= deadline:  # the window closed before this agent's turn began
                return _turn_result(member, TurnOutcome.NOT_REACHED)
            return await _ask_and_write(member, path)

    async def _turn(member: CrewMember) -> TurnResult:
        try:
            return await _claimed_turn(member)
        except Exception:  # A2 (M2-6): one member's fault never ends the others' turns or the report
            logger.warning(
                "AD-1341 S4: %s's stand-down turn failed; nothing is written", member.callsign or member.agent_id,
                exc_info=True,
            )
            return _turn_result(member, TurnOutcome.FAILED)

    turns = [asyncio.create_task(_turn(member)) for member in crew]  # A4: held here and drained below
    try:
        await asyncio.gather(*turns)
    except BaseException:  # A2 (M2-6): the caller's cancellation, or a turn's own; no turn outlives the stand-down
        for turn in turns:
            turn.cancel()
        await asyncio.gather(*turns, return_exceptions=True)
        raise
    report = StandDownReport(timeline_id=timeline_id, turns=tuple(turn.result() for turn in turns))
    logger.info(
        "AD-1341 S4: stand-down for timeline %s: %d of %d crew agents left exit notes",
        timeline_id, report.count(TurnOutcome.WRITTEN), len(report.turns),
    )
    return report


def crew_for_stand_down(runtime: Any) -> tuple[CrewMember, ...]:
    """Every crew agent in the registry (AD-429e's crew types) with the identity ``IdentityService`` resolves (D9)."""
    from probos.crew_utils import is_crew_agent

    identities = runtime.identity_service
    members: list[CrewMember] = []
    for agent in runtime.registry.all():
        if not is_crew_agent(agent, runtime.ontology):
            continue
        ref = identities.resolve(agent.id) if identities is not None else None
        members.append(CrewMember(
            agent_id=agent.id,
            agent_type=agent.agent_type,
            sovereign_id=ref.sovereign_id if ref is not None else "",
            did=ref.did if ref is not None else "",
            callsign=ref.callsign if ref is not None else "",
        ))
    return tuple(sorted(members, key=lambda member: (member.agent_type, member.agent_id)))


async def stand_down_vessel(runtime: Any) -> StandDownReport:
    """The Captain's ``/stand-down`` on this vessel: refuse, or give each crew agent its one turn (D2, D3)."""
    if not runtime.config.archive.enabled:
        raise StandDownRefused("The Ship's Archive is disabled (archive.enabled), so no exit note would be archived.")
    records = runtime.records_store
    if records is None:
        raise StandDownRefused("Ship's Records is not running, so no exit note could be kept.")
    ontology = runtime.ontology
    timeline_id = ontology.get_vessel_identity().instance_id if ontology is not None else ""
    if not timeline_id or timeline_id == "unknown":  # the ontology's placeholder when no identity is loaded
        raise StandDownRefused("This vessel has no instance id, so its exit notes could not be attributed to a timeline.")
    bus, memory = runtime.intent_bus, runtime.episodic_memory

    async def _ask(member: CrewMember, text: str) -> str | None:
        intent = IntentMessage(
            intent="direct_message",
            params={"text": text, "from": "captain", "session": False, BOUNDED_TURN_PARAM: True},  # A2 (M2-1)
            target_agent_id=member.agent_id,
            ttl_seconds=STAND_DOWN_TURN_SECONDS,
        )
        result = await bus.send(intent)
        if result is None or not result.success:  # refused, stopped or failed: no turn
            return None
        return DmReply.from_intent_result(result).body

    async def _recall(member: CrewMember) -> Sequence[Any]:
        if memory is None or not member.sovereign_id:
            return ()
        return await memory.recent_for_agent(member.sovereign_id, k=STAND_DOWN_EPISODES)

    return await run_stand_down(
        crew_for_stand_down(runtime), ask=_ask, recall=_recall, records=records, timeline_id=timeline_id,
    )
```

### 7.7 New file: `src/probos/experience/commands/commands_stand_down.py` (M2)

```python
"""AD-1341 S4 (#1569): ``/stand-down``, the Captain's order giving each crew agent one bounded turn to leave exit notes.

Console only (``probos.api._BLOCKED_COMMANDS``). Typed before the vessel is stopped for ``probos reset``; the reset
neither needs it nor waits for it.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape


async def cmd_stand_down(runtime: Any, console: Console, arg: str) -> None:
    """Run the stand-down, then report each crew agent's turn and the Captain's next steps (D13)."""
    from probos.stand_down import (
        STAND_DOWN_TURN_SECONDS,
        STAND_DOWN_WINDOW_SECONDS,
        StandDownRefused,
        TurnOutcome,
        stand_down_vessel,
    )

    if arg.strip():
        console.print("Usage: /stand-down  (no arguments)")
        return
    console.print(
        f"Standing down: each crew agent gets one turn of at most {STAND_DOWN_TURN_SECONDS:.0f} s to leave exit notes "
        f"for its successor; the window closes after {STAND_DOWN_WINDOW_SECONDS:.0f} s. Writing is optional."
    )
    try:
        report = await stand_down_vessel(runtime)
    except StandDownRefused as exc:
        console.print(f"[yellow]Stand-down refused: {escape(str(exc))}[/yellow]")
        return
    for turn in report.turns:
        where = f" -> {turn.path}" if turn.path else ""
        console.print(f"  {escape(turn.callsign or turn.agent_type)}: {turn.outcome.value}{escape(where)}")
    left = sum(1 for turn in report.turns if turn.path and turn.outcome in (TurnOutcome.FAILED, TurnOutcome.TIMED_OUT))
    if left:  # A5 (round 3 M2-2): a write that did not complete may still have published its note
        console.print(
            f"{left} write(s) did not complete and may have left a document at the path shown; "
            "probos archive pending lists any the next reset would archive."
        )
    console.print(
        f"{report.count(TurnOutcome.WRITTEN)} exit note(s) written for timeline {escape(report.timeline_id)}. "
        "Review: probos archive pending. Veto one: probos archive veto PATH --reason TEXT. "
        "Then stop the vessel and run probos reset."
    )
```

### 7.8 `src/probos/experience/shell.py` (M2)

Pair 1 (import):

SEARCH:
```python
from probos.experience.commands import commands_schedule  # AD-812
```
REPLACE:
```python
from probos.experience.commands import commands_schedule  # AD-812
from probos.experience.commands import commands_stand_down  # AD-1341 S4
```

Pair 2 (help):

SEARCH:
```python
        "/schedule":  "Schedule from natural language (/schedule <NL> | list | cancel <id>) — AD-812",
```
REPLACE:
```python
        "/schedule":  "Schedule from natural language (/schedule <NL> | list | cancel <id>) — AD-812",
        "/stand-down": "Each crew agent's one bounded turn to leave exit notes before a reset (console only) — AD-1341",
```

Pair 3 (dispatch):

SEARCH:
```python
            "/schedule":   lambda: commands_schedule.cmd_schedule(rt, con, arg),
```
REPLACE:
```python
            "/schedule":   lambda: commands_schedule.cmd_schedule(rt, con, arg),
            "/stand-down": lambda: commands_stand_down.cmd_stand_down(rt, con, arg),
```

### 7.9 `src/probos/api.py` (M2)

SEARCH:
```python
# Commands that should NOT be available via the API
_BLOCKED_COMMANDS = {'/quit', '/debug'}
```
REPLACE:
```python
# Commands that should NOT be available via the API
# AD-1341 S4: /stand-down gives every crew agent a model turn for minutes. The HXI chat and the channel adapters reach
# this function without the Captain's console, so it runs only at the console (probos serve --interactive).
_BLOCKED_COMMANDS = {'/quit', '/debug', '/stand-down'}
```

### 7.9a `src/probos/cognitive/cognitive_agent.py` (M2, A2)

A2 (M2-1). The stand-down's `direct_message` carries `bounded_turn: True` (7.6, `BOUNDED_TURN_PARAM`). `_conversational_agentic_will_run` (`:4692-4715`) is the one gate for the conversational agentic loop; its readers are the dispatch `_maybe_run_conversational_agentic` (`:4754`, called by the decision step at `:4382`), the AD-1070 self-description (`:3214`) and the two reply-tag suppressions (`:4206`, `:4254`). Answering no for a bounded turn sends it down the single-pass path, as a DM goes today with `dm_agentic.enabled` false: no tool array, no `WorkItemAgenticExecutor`, no AD-1165 promotion (`:5190-5205`, `run_with_promotion` `:5404`). No other sender sets the param (§5), so no other DM changes. No method and no callee is added: the SRP count and the AD-1343 census hold. A shared contract: round 2 re-reviews whole.

Pair 1 (the gate's docstring):

SEARCH:
```python
        ``config.dm_agentic.enabled``, a 1:1 ``direct_message`` (not group /
        ward-room / proactive), and no vision (multimodal turns are single-pass).
```
REPLACE:
```python
        ``config.dm_agentic.enabled``, a 1:1 ``direct_message`` (not group /
        ward-room / proactive), and no vision (multimodal turns are single-pass).
        AD-1341 S4 (A2): and not a bounded turn (``params["bounded_turn"] is
        True``, the stand-down's exit-notes message): its sender bounds and
        cancels the turn, so it is answered inline on the single-pass path and
        never promoted into a background work item (AD-1165) past that bound.
```

Pair 2 (the gate):

SEARCH:
```python
        if params.get("vision_messages"):
            return False
        return True
```
REPLACE:
```python
        if params.get("vision_messages"):
            return False
        if params.get("bounded_turn") is True:  # AD-1341 S4 (A2): probos.stand_down.BOUNDED_TURN_PARAM
            return False
        return True
```

### 7.10 New file: `tests/test_ad1341_s4_stand_down.py` (M2)

```python
"""AD-1341 S4 M2 (#1569): the stand-down gives each crew agent one bounded, optional turn and keeps what it writes.

The service runs for real over real Ship's Records (S1's ``_records``); an agent's turn is a stub ``ask``, the only
stand-in for a model. The vessel tests (S11 to S13b, S15) run ``stand_down_vessel`` over a real ``IntentBus`` whose
subscribers answer the Captain's message as a crew agent's model would, the in-memory ``MockEpisodicMemory`` and an
identity stub returning real ``IdentityRef`` values. S15 then runs the real ``probos reset`` (S1's ``_reset``), a later
crew's real Oracle (S1's ``_oracle_query``) and S3's real AD-754 citation check.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import errno
import json
import re
import subprocess
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

import probos
from probos.api import _handle_slash_command
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.llm_client import BaseLLMClient
from probos.consensus.trust import TrustNetwork
from probos.experience.commands import commands_stand_down
from probos.experience.shell import ProbOSShell
from probos.identity_service import IdentityRef
from probos.knowledge.archive_promotion import plan_promotion
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_CALLSIGN_MAX_CHARS,
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTES_DIR,
    LESSON_MAX_CHARS,
    LESSON_SECTIONS,
    exit_note_body,
    exit_note_path,
)
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.stand_down import (
    BOUNDED_TURN_PARAM,
    EPISODE_EXCERPT_CHARS,
    STAND_DOWN_CONCURRENCY,
    STAND_DOWN_TURN_SECONDS,
    CrewMember,
    StandDownRefused,
    TurnOutcome,
    crew_for_stand_down,
    exit_notes_prompt,
    run_stand_down,
    stand_down_vessel,
)
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThreadStore
from probos.types import Episode, IntentMessage, IntentResult, LLMResponse
from probos.workforce import WorkItemStore
from tests.test_ad1341_s1_reset_and_erase import (
    _SHIP,
    _archive_store,
    _config,
    _data_dir,
    _oracle_query,
    _records,
    _reset,
    _rows,
)
from tests.test_ad1341_s4_lessons import _DID, _LESSON, _deny_entry_type, _deny_listing, _deny_reading

_SRC = Path(probos.__file__).resolve().parent


def _member(
    agent_type: str = "surgeon", callsign: str = "Chapel", did: str = _DID, sovereign: str = "sov-surgeon",
) -> CrewMember:
    return CrewMember(
        agent_id=f"slot-{agent_type}", agent_type=agent_type, sovereign_id=sovereign, did=did, callsign=callsign,
    )


def _episodes(count: int, sovereign: str = "sov-surgeon") -> list[Episode]:
    """``count`` episodes of one agent, oldest first; each opens with far more than an excerpt's characters."""
    return [
        Episode(
            id=f"ep-{index:03d}",
            timestamp=1_790_000_000.0 + index,
            agent_ids=[sovereign],
            user_input=f"Night watch {index}: the coolant drift alarm cleared again. " + "Readings logged. " * 20,
        )
        for index in range(count)
    ]


def _reply(cites: str = "e1, e2") -> str:
    """A reply in the lessons format, with a preamble and a citations line that the note never keeps."""
    return f"Here are my notes.\n\n{_LESSON.render()}\nCites: {cites}\n"


async def _no_episodes(member: CrewMember) -> list[Episode]:
    return []


async def _run(records: Any, crew: tuple[CrewMember, ...], ask: Any, recall: Any = _no_episodes, **bounds: Any) -> Any:
    return await run_stand_down(crew, ask=ask, recall=recall, records=records, timeline_id=_SHIP, **bounds)


async def _notes(records: Any) -> list[str]:
    return sorted(entry["path"] for entry in await records.list_entries(EXIT_NOTES_DIR))


def _handler(agent_id: str, reply: str | None, received: list[IntentMessage]) -> Any:
    async def _handle(intent: IntentMessage) -> IntentResult:
        received.append(intent)
        if reply is None:  # the agent refused or failed its turn
            return IntentResult(intent_id=intent.id, agent_id=agent_id, success=False, error="no turn")
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=reply, confidence=1.0)

    return _handle


def _vessel(
    config: Any, records: Any, memory: Any, *, replies: dict[str, tuple[str, str | None]], instance_id: str = _SHIP,
) -> tuple[SimpleNamespace, list[IntentMessage]]:
    """A running vessel as the stand-down reads it: crew agents on a real intent bus, and one utility agent."""
    bus = IntentBus(SignalManager())
    received: list[IntentMessage] = []
    agents = [SimpleNamespace(id="slot-file_reader", agent_type="file_reader")]  # not crew: never addressed
    refs: dict[str, IdentityRef] = {}
    for agent_type, (callsign, reply) in replies.items():
        agent_id = f"slot-{agent_type}"
        agents.append(SimpleNamespace(id=agent_id, agent_type=agent_type))
        refs[agent_id] = IdentityRef(
            slot_id=agent_id, sovereign_id=f"sov-{agent_type}", did=f"did:probos:{_SHIP}:{agent_type}",
            callsign=callsign, agent_type=agent_type,
        )
        bus.subscribe(agent_id, _handler(agent_id, reply, received), intent_names=["direct_message"])
    ontology = SimpleNamespace(
        get_vessel_identity=lambda: SimpleNamespace(instance_id=instance_id),
        get_crew_agent_types=lambda: set(replies),
    )
    runtime = SimpleNamespace(
        config=config, records_store=records, ontology=ontology, registry=SimpleNamespace(all=lambda: list(agents)),
        identity_service=SimpleNamespace(resolve=refs.get), intent_bus=bus, episodic_memory=memory,
    )
    return runtime, received


# --- S1 to S2: one turn each, and what is kept ----------------------------------------------------------------------


async def test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    async def recall(member: CrewMember) -> list[Episode]:
        return _episodes(3, member.sovereign_id)

    crew = (_member(), _member("data_analyst", "Rahda", f"did:probos:{_SHIP}:rahda-0001", "sov-data_analyst"))
    report = await _run(records, crew, ask, recall)

    assert [(turn.agent_type, turn.outcome) for turn in report.turns] == [
        ("surgeon", TurnOutcome.WRITTEN), ("data_analyst", TurnOutcome.WRITTEN),
    ]
    assert sorted(asked) == ["data_analyst", "surgeon"]  # one turn each
    path = exit_note_path(_SHIP, "surgeon")
    assert (report.timeline_id, report.turns[0].path) == (_SHIP, path)
    note = await records.read_entry(path, "captain")
    frontmatter = note["frontmatter"]
    assert (frontmatter["author"], frontmatter["classification"], frontmatter["status"]) == (
        "Chapel", "ship", EXIT_NOTE_STATUS,
    )
    assert frontmatter[EXIT_NOTE_KEY] == {
        "version": 1, "timeline_id": _SHIP, "callsign": "Chapel", "agent_type": "surgeon", "author_did": _DID,
        "source_episode_ids": ["ep-000", "ep-001"],
    }
    # The note is its origin line and the lesson: never the reply's preamble or citations line, never episode text.
    assert note["content"] == exit_note_body("Chapel", "surgeon", _SHIP, _LESSON)
    assert "Night watch" not in note["content"] and "Cites:" not in note["content"]


@pytest.mark.parametrize(
    "case, outcome",
    [
        ("declined", TurnOutcome.DECLINED), ("not-in-format", TurnOutcome.NOT_IN_FORMAT),
        ("no-reply", TurnOutcome.NO_REPLY), ("failed", TurnOutcome.FAILED),
    ],
)
async def test_writing_is_optional_and_a_turn_that_leaves_no_lesson_writes_nothing(
    tmp_path: Path, case: str, outcome: TurnOutcome,
) -> None:
    records = _records(_data_dir(tmp_path))

    async def ask(member: CrewMember, prompt: str) -> str | None:
        if case == "failed":
            raise RuntimeError("the model call failed")
        return {"declined": DECLINE_REPLY, "not-in-format": "A few thoughts, unsorted.", "no-reply": None}[case]

    report = await _run(records, (_member(),), ask)

    assert [turn.outcome for turn in report.turns] == [outcome]
    assert await _notes(records) == []


@pytest.mark.parametrize("case", ["published", "replaced", "not-published"])
async def test_a_write_that_fails_after_publishing_leaves_no_hidden_note(tmp_path: Path, case: str) -> None:
    """A2 (M2-4), A4: ``write_entry`` publishes the document before git runs, so its failure can follow the
    publication (a git timeout here, as the real call raises past its 30 s). The stand-down never removes a document:
    a note the failed write published is reported failed WITH its path, the Captain's review lists it and the next
    promotion would archive it; a document another writer put at the path stays exactly as it is; a write that failed
    before publishing leaves nothing, and the next stand-down asks again."""
    records = _records(_data_dir(tmp_path))
    real_write = records.write_entry
    failures = [1]

    async def write_entry(**fields: Any) -> Any:
        if failures:
            failures.pop()
            if case == "not-published":
                raise OSError("Ship's Records' disk is full")  # fails before anything is written
            if case == "replaced":  # another writer's document is at the path when the git failure comes
                fields = {**fields, "author": "Bones", "content": "Written by hand.", "extra_frontmatter": None}
            await real_write(**fields)  # published
            raise subprocess.TimeoutExpired(["git", "add"], 30)
        return await real_write(**fields)

    records.write_entry = write_entry  # type: ignore[method-assign]

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    path = exit_note_path(_SHIP, "surgeon")
    report = await _run(records, (_member(),), ask)

    if case == "not-published":
        assert [(turn.outcome, turn.path) for turn in report.turns] == [(TurnOutcome.FAILED, "")]
        assert await _notes(records) == []
        again = await _run(records, (_member(),), ask)  # nothing was left, so the billet is asked again
        assert [(turn.outcome, turn.path) for turn in again.turns] == [(TurnOutcome.WRITTEN, path)]
        return
    assert [(turn.outcome, turn.path) for turn in report.turns] == [(TurnOutcome.FAILED, path)]
    note = await records.read_entry(path, "captain")
    selected = [record.source_ref for record in (await plan_promotion(records, timeline_id=_SHIP)).records]
    if case == "published":  # the agent's whole note, named in the report: reviewable, vetoable, archivable
        assert selected == [path]
    else:  # never removed and never rewritten
        assert (note["frontmatter"]["author"], note["content"], selected) == ("Bones", "Written by hand.", [])


async def test_a_failed_write_whose_note_cannot_be_checked_still_names_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A5 (round 3 M2-4): a write publishes its note and then fails, and whether the note is there cannot be told
    (``Path.lstat`` of the billet raises). Unknown counts as there, so the report names the path for the Captain's
    review; dropping that fallback hid a note the next reset would archive (rows D-43, D-46)."""
    records = _records(_data_dir(tmp_path))
    real_write, real_lstat = records.write_entry, Path.lstat
    path = exit_note_path(_SHIP, "surgeon")
    checks: list[str] = []

    def lstat(self: Path) -> Any:
        if self.name == "surgeon.md":
            checks.append(str(self))
            raise PermissionError(13, "the volume is being checked", str(self))
        return real_lstat(self)

    async def write_entry(**fields: Any) -> Any:
        await real_write(**fields)  # published
        monkeypatch.setattr(Path, "lstat", lstat)  # from here no check of the billet can be made
        raise subprocess.TimeoutExpired(["git", "add"], 30)

    records.write_entry = write_entry  # type: ignore[method-assign]

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    report = await _run(records, (_member(),), ask)
    monkeypatch.undo()

    assert checks  # premise: the check after the failure was made, and could not tell
    assert [(turn.outcome, turn.path) for turn in report.turns] == [(TurnOutcome.FAILED, path)]
    assert len((await plan_promotion(records, timeline_id=_SHIP)).records) == 1  # the note the path names


# --- S3 to S6: the bounds -------------------------------------------------------------------------------------------


async def test_a_turn_that_runs_past_its_bound_is_cancelled_and_writes_nothing(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    cancelled = asyncio.Event()

    async def ask(member: CrewMember, prompt: str) -> str:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _reply()

    started = time.monotonic()
    report = await _run(records, (_member(),), ask, turn_seconds=1.5, window_seconds=60.0)
    elapsed = time.monotonic() - started

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert 1.4 <= elapsed < 2.5  # A2 (M2-9), A3 (2): the turn's own bound, neither halved nor doubled, 1 s headroom
    assert cancelled.is_set()  # the turn is cancelled, never left running
    assert await _notes(records) == []


async def test_a_reply_that_returns_after_the_turn_s_deadline_writes_nothing(tmp_path: Path) -> None:
    """A2 (M2-5): an ask that suppresses its cancellation and returns after the turn's deadline, inside the window."""
    records = _records(_data_dir(tmp_path))

    async def ask(member: CrewMember, prompt: str) -> str:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(0.1)  # finishes late instead of stopping
        return _reply()

    report = await _run(records, (_member(),), ask, turn_seconds=0.2, window_seconds=60.0)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert await _notes(records) == []


@pytest.mark.parametrize("case", ["slow-recall", "recall-runs-out"])
async def test_the_recall_and_the_ask_spend_one_turn(tmp_path: Path, case: str) -> None:
    """A2 (M2-5): one deadline per turn. What the recall spent is not given back to the ask, and a recall that runs
    out the turn leaves no turn to ask in.

    A3 (2): the turn runs on the stand-down's ``clock``, which the stubs advance, so the recall's end, the ask and the
    turn's deadline come in one fixed order, never raced against the event loop's timer resolution."""
    records = _records(_data_dir(tmp_path))
    now = [0.0]
    asked: list[str] = []

    async def recall(member: CrewMember) -> list[Episode]:
        if case == "slow-recall":
            now[0] = 0.3  # the recall spent 0.3 s of the 0.5 s turn
            return []
        try:
            await asyncio.sleep(5)  # hangs until the turn's bound cancels it
        except asyncio.CancelledError:
            now[0] = 0.6  # the turn is spent; the 60 s window is not
            raise
        return []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        now[0] += 0.35  # inside a fresh 0.5 s turn, past what the recall left
        return _reply()

    report = await _run(
        records, (_member(),), ask, recall, turn_seconds=0.5, window_seconds=60.0, clock=lambda: now[0],
    )

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert asked == (["surgeon"] if case == "slow-recall" else [])
    assert await _notes(records) == []


async def test_the_window_closes_on_time_and_writes_nothing_late_or_unreached(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    now = [0.0]
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        if member.agent_type == "data_analyst":
            now[0] = 1_000.0  # this reply arrives after the 60-second window has closed
        return _reply()

    crew = (
        _member(),
        _member("data_analyst", "Rahda", "did:probos:x:rahda", "sov-data_analyst"),
        _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist"),
    )
    report = await _run(records, crew, ask, window_seconds=60.0, concurrency=1, clock=lambda: now[0])

    assert [turn.outcome for turn in report.turns] == [
        TurnOutcome.WRITTEN, TurnOutcome.TIMED_OUT, TurnOutcome.NOT_REACHED,
    ]
    assert asked == ["surgeon", "data_analyst"]  # the agent the window did not reach was never asked
    assert await _notes(records) == [exit_note_path(_SHIP, "surgeon")]


async def test_the_window_bounds_a_turn_its_own_bound_would_allow(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))

    async def ask(member: CrewMember, prompt: str) -> str:
        await asyncio.sleep(5)
        return _reply()

    started = time.monotonic()
    report = await _run(records, (_member(),), ask, turn_seconds=60.0, window_seconds=1.5)
    elapsed = time.monotonic() - started

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert 1.4 <= elapsed < 2.5  # A2 (M2-9), A3 (2): the window's bound, neither halved nor doubled, 1 s headroom
    assert await _notes(records) == []


@pytest.mark.parametrize("stage", ["first-read", "write"])
async def test_the_window_bounds_the_records_reads_and_writes_too(tmp_path: Path, stage: str) -> None:
    """A2 (M2-2): the window starts before Ship's Records is first read and cuts off every write still awaiting. A
    first read that hangs refuses the stand-down with nobody asked; a write that hangs ends with the window, and the
    turn queued behind it for the write lock never starts a write.

    A4 (round 2 M2-7): this proves the write lock's guard on the injected clock, not the real timer. On the real
    clock the queued turn may begin a write in that last tick; the window then cuts it off and the report names any
    note it left. S4d proves those guarantees on the real clock.

    A3 (2): the window runs on the stand-down's ``clock``. The hanging write moves it past the deadline when the
    window's bound cancels the write, so the queued turn finds the window closed in every run; on the real clock,
    asyncio may fire the bound one clock tick early (15.6 ms on Windows before Python 3.13) and leave that turn a
    few milliseconds of window to begin a write in. A write is counted when ``write_entry`` is called: a write whose
    bound is already spent is cancelled before its coroutine runs."""
    records = _records(_data_dir(tmp_path))
    real_list, real_write = records.list_entries, records.write_entry
    now = [0.0]
    writes: list[str] = []
    asked: list[str] = []

    async def list_entries(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(5)
        return await real_list(*args, **kwargs)

    async def _hang(fields: dict[str, Any]) -> Any:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            now[0] = 1_000.0  # the window's bound cancelled the write: the window has closed
            raise
        return await real_write(**fields)

    def write_entry(**fields: Any) -> Any:
        writes.append(fields["path"])  # at the call, before anything awaits the write
        return _hang(fields)

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    crew = (_member(), _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist"))
    started = time.monotonic()
    if stage == "first-read":
        records.list_entries = list_entries  # type: ignore[method-assign]
        with pytest.raises(StandDownRefused, match="Ship's Records could not be read in time"):
            await _run(records, crew, ask, window_seconds=0.3)
        records.list_entries = real_list  # type: ignore[method-assign]
        assert asked == []
    else:
        records.write_entry = write_entry  # type: ignore[method-assign]
        report = await _run(records, crew, ask, window_seconds=0.3, clock=lambda: now[0])
        assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT, TurnOutcome.TIMED_OUT]
        assert len(writes) == 1  # the turn behind the lock never began a write
    assert time.monotonic() - started < 3.0
    assert await _notes(records) == []


async def test_a_first_read_that_returns_after_the_window_asks_nobody_and_starts_no_turn(tmp_path: Path) -> None:
    """A5 (round 3 M2-3): ``asyncio.wait_for`` cannot cut off a first read that never yields (synchronous Ship's
    Records I/O, register R22). When it returns after the window has closed, the stand-down refuses before it creates
    a turn task, so nobody is asked and nothing begins after the window. The injected clock moves inside the read."""
    records = _records(_data_dir(tmp_path))
    real_list = records.list_entries
    now = [0.0]
    asked: list[str] = []

    async def list_entries(*args: Any, **kwargs: Any) -> Any:
        listed = await real_list(*args, **kwargs)  # the real store's read never yields
        now[0] = 1_000.0  # and it took longer than the whole window
        return listed

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    records.list_entries = list_entries  # type: ignore[method-assign]
    with pytest.raises(StandDownRefused, match="took the whole stand-down window, so nobody was asked"):
        await _run(records, (_member(),), ask, window_seconds=0.3, clock=lambda: now[0])

    assert asked == []
    assert await _notes(records) == []


@pytest.mark.parametrize("case", ["the-check-outlasts-the-window", "a-write-returns-late", "cut-off-after-publishing"])
async def test_on_the_real_clock_no_write_begins_after_the_window_and_every_note_left_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    """A4 (round 2 M2-2, M2-4, M2-7): the real clock, with 200 ms of margin over Windows' 15.6 ms tick; no assertion
    but the upper bound rests on an asyncio timer.

    The check for a note written meanwhile is charged to the window: a check that outlasts it begins no write. A
    write that returns after the window (synchronous Ship's Records I/O, register R22) left its note, so the report
    says written and names it. A write the window cuts off after it published is timed out, and the report names
    the note it left, which the next promotion would archive unless the Captain vetoes it."""
    records = _records(_data_dir(tmp_path))
    real_write, real_lstat = records.write_entry, Path.lstat
    path = exit_note_path(_SHIP, "surgeon")
    writes: list[str] = []

    def lstat(self: Path) -> Any:  # A5: the check asks Path.lstat (_present)
        if case == "the-check-outlasts-the-window" and self.name == "surgeon.md":
            time.sleep(0.4)  # a slow filesystem: the 0.2 s window closes during the check
        return real_lstat(self)

    async def write_entry(**fields: Any) -> Any:
        writes.append(fields["path"])
        await real_write(**fields)  # published; with auto_commit off the store awaits nothing
        if case == "a-write-returns-late":
            time.sleep(0.4)  # synchronous I/O the window cannot pre-empt (R22)
        elif case == "cut-off-after-publishing":
            await asyncio.sleep(5)  # the commit hangs, and the window's bound cancels it
        return fields["path"]

    monkeypatch.setattr(Path, "lstat", lstat)
    records.write_entry = write_entry  # type: ignore[method-assign]

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    started = time.monotonic()
    report = await _run(records, (_member(),), ask, window_seconds=0.2)
    elapsed = time.monotonic() - started
    monkeypatch.undo()

    left = case != "the-check-outlasts-the-window"
    outcome = TurnOutcome.WRITTEN if case == "a-write-returns-late" else TurnOutcome.TIMED_OUT
    assert [(turn.outcome, turn.path) for turn in report.turns] == [(outcome, path if left else "")]
    assert writes == ([path] if left else [])
    assert await _notes(records) == ([path] if left else [])
    assert len((await plan_promotion(records, timeline_id=_SHIP)).records) == int(left)
    assert elapsed < 1.5


async def test_a_cancelled_stand_down_keeps_every_note_it_published_and_leaves_nothing_running(
    tmp_path: Path,
) -> None:
    """A4 (round 2 M2-3): the Captain's cancellation, or the vessel stopping, ends the stand-down without a report.
    Nothing it published is removed: the note whose commit the cancellation cut short is whole (Ship's Records writes
    the file before it awaits git), as every note written before it is, and the Captain's review lists it (register
    R27). The cancellation propagates, and no turn outlives the call."""
    records = _records(_data_dir(tmp_path))
    real_write = records.write_entry
    published = asyncio.Event()
    path = exit_note_path(_SHIP, "surgeon")
    before = asyncio.all_tasks()

    async def write_entry(**fields: Any) -> Any:
        await real_write(**fields)  # published
        published.set()
        await asyncio.sleep(5)  # the commit is still running when the stand-down is cancelled
        return fields["path"]

    records.write_entry = write_entry  # type: ignore[method-assign]

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    stand_down = asyncio.create_task(_run(records, (_member(),), ask))
    await asyncio.wait_for(published.wait(), timeout=5.0)
    stand_down.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stand_down

    assert asyncio.all_tasks() - before == set()
    assert await _notes(records) == [path]
    assert [record.source_ref for record in (await plan_promotion(records, timeline_id=_SHIP)).records] == [path]


async def test_no_more_than_the_bounded_number_of_turns_run_at_once(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    running = [0, 0]  # now, peak

    async def ask(member: CrewMember, prompt: str) -> None:
        running[0] += 1
        running[1] = max(running[1], running[0])
        await asyncio.sleep(0.05)
        running[0] -= 1
        return None

    crew = tuple(_member(f"type_{index}", f"C{index}", f"did:probos:x:{index}", f"sov-{index}") for index in range(5))
    report = await _run(records, crew, ask)

    assert report.count(TurnOutcome.NO_REPLY) == 5
    assert running[1] == STAND_DOWN_CONCURRENCY == 2


async def test_the_stand_down_writes_one_note_at_a_time(tmp_path: Path) -> None:
    """A1: two turns run at once (concurrency 2), and their Ship's Records writes never overlap (7.6's write lock)."""
    records = _records(_data_dir(tmp_path))
    real_write, writing = records.write_entry, [0, 0]  # now, peak

    async def write_entry(**fields: Any) -> Any:
        writing[0] += 1
        writing[1] = max(writing[1], writing[0])
        try:
            await asyncio.sleep(0.05)  # hold the write open, so an unserialised second write would overlap it
            return await real_write(**fields)
        finally:
            writing[0] -= 1

    records.write_entry = write_entry  # type: ignore[method-assign]  # the real store's write, observed

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    crew = tuple(_member(f"type_{index}", f"C{index}", f"did:probos:x:{index}", f"sov-{index}") for index in range(3))
    report = await _run(records, crew, ask)

    assert report.count(TurnOutcome.WRITTEN) == 3
    assert writing[1] == 1
    assert len(await _notes(records)) == 3


# --- S7 to S10: citations, idempotence, the prompt, identity --------------------------------------------------------


async def test_a_note_cites_only_episodes_the_agent_was_shown(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    prompts: list[str] = []

    async def recall(member: CrewMember) -> list[Episode]:
        return _episodes(13, member.sovereign_id)

    async def ask(member: CrewMember, prompt: str) -> str:
        prompts.append(prompt)
        return _reply("e1, e12, e13, e99, e1")

    report = await _run(records, (_member(),), ask, recall)

    shown = [line for line in prompts[0].splitlines() if re.match(r"^e\d+ ", line)]
    assert [line.split()[0] for line in shown] == [f"e{index}" for index in range(1, 13)]
    assert all(len(line.split(": ", 1)[1]) <= EPISODE_EXCERPT_CHARS for line in shown)
    note = await records.read_entry(report.turns[0].path, "captain")
    assert note["frontmatter"][EXIT_NOTE_KEY]["source_episode_ids"] == ["ep-000", "ep-011"]


async def test_a_failed_episode_read_offers_none_and_the_note_cites_none(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))

    async def recall(member: CrewMember) -> list[Episode]:
        raise OSError("the episodic store is unavailable")

    async def ask(member: CrewMember, prompt: str) -> str:
        assert "(none could be read)" in prompt
        return _reply("e1")

    report = await _run(records, (_member(),), ask, recall)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.WRITTEN]
    note = await records.read_entry(report.turns[0].path, "captain")
    assert note["frontmatter"][EXIT_NOTE_KEY]["source_episode_ids"] == []


@pytest.mark.parametrize(
    "bad_id",
    ["e" * (EXIT_NOTE_EPISODE_ID_MAX_CHARS + 1), "ep\x00bad", "ep-\ud800", "ep\nbad", "ep---bad"],
    ids=["long", "nul", "surrogate", "line-break", "delimiter"],
)
async def test_every_episode_offered_can_be_cited_by_a_note_the_promotion_archives(
    tmp_path: Path, bad_id: str,
) -> None:
    """A4 (R2-F4, M2-5): an episode whose id the promotion's rule refuses is never offered or shown, so citing what
    was offered never turns a written note into one the promotion withholds. Every offered id is cited, stored and
    archived."""
    records = _records(_data_dir(tmp_path))
    prompts: list[str] = []

    async def recall(member: CrewMember) -> list[Episode]:
        bad = Episode(id=bad_id, timestamp=1_790_000_000.0, agent_ids=[member.sovereign_id], user_input="the bad one")
        return [bad, *_episodes(2, member.sovereign_id)]

    async def ask(member: CrewMember, prompt: str) -> str:
        prompts.append(prompt)
        return _reply("e1, e2, e3")

    report = await _run(records, (_member(),), ask, recall)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.WRITTEN]
    assert "the bad one" not in prompts[0]  # never shown
    plan = await plan_promotion(records, timeline_id=_SHIP)
    assert [record.source_episode_ids for record in plan.records] == [("ep-000", "ep-001")]


@pytest.mark.parametrize("script", ["ascii", "cjk", "astral"])
async def test_the_captain_s_message_stays_inside_the_inline_params_bound_in_any_script(
    tmp_path: Path, script: str,
) -> None:
    """A2 (M2-8): 12 episodes in any script and a callsign at its bound in CJK. The Captain's message as the transport
    encodes it (JSON, every character outside ASCII escaped) stays inside the 4 KiB standard for inline params, and
    the agent is still shown all 12."""
    letter = {"ascii": "a", "cjk": "\u6f22", "astral": "\U0001f680"}[script]
    data_dir = _data_dir(tmp_path)
    memory = MockEpisodicMemory()
    for index in range(12):
        await memory.store(Episode(
            id=f"ep-{index:03d}", timestamp=1_790_000_000.0 + index, agent_ids=["sov-surgeon"],
            user_input=f"{index} " + letter * 400,
        ))
    callsign = "\u5c0f" * EXIT_NOTE_CALLSIGN_MAX_CHARS
    runtime, received = _vessel(_config(tmp_path), _records(data_dir), memory, replies={"surgeon": (callsign, None)})

    await stand_down_vessel(runtime)

    (intent,) = received
    shown = [line for line in intent.params["text"].splitlines() if re.match(r"^e\d+ ", line)]
    assert len(shown) == 12
    assert len(json.dumps(intent.params)) <= 4096


class _Unrenderable:
    """An episode whose text cannot even be read (a store returning a broken record)."""

    id = "ep-broken"
    timestamp = 1_790_000_000.0

    @property
    def user_input(self) -> str:
        raise RuntimeError("the episode's text cannot be read")


@pytest.mark.parametrize("case", ["timestamps", "unreadable-episode", "self-cancelled"])
async def test_one_member_s_fault_never_ends_the_other_turns_or_leaves_one_running(tmp_path: Path, case: str) -> None:
    """A2 (M2-6): a timestamp that names no date (inf, NaN) is shown undated; an episode whose text cannot be read
    fails that member's turn only; a turn cancelled from inside ends the stand-down with every other turn cancelled
    and drained. Nothing outlives the call."""
    records = _records(_data_dir(tmp_path))
    stopped = asyncio.Event()
    before = asyncio.all_tasks()

    async def recall(member: CrewMember) -> list[Any]:
        if member.agent_type == "surgeon" and case == "unreadable-episode":
            return [_Unrenderable()]
        stamps = (float("inf"), float("nan")) if case == "timestamps" else (1_790_000_000.0,)
        return [
            Episode(id=f"ep-{index}", timestamp=stamp, agent_ids=[member.sovereign_id], user_input="watch")
            for index, stamp in enumerate(stamps)
        ]

    async def ask(member: CrewMember, prompt: str) -> str:
        if case == "self-cancelled":
            if member.agent_type == "surgeon":
                await asyncio.sleep(0.05)  # the other turn is waiting on its model by now
                raise asyncio.CancelledError  # cancelled from inside the turn, not by the caller
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                stopped.set()
                raise
        if case == "timestamps":
            assert "undated" in prompt
        return _reply()

    crew = (_member(), _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist"))
    if case == "self-cancelled":
        with pytest.raises(asyncio.CancelledError):
            await _run(records, crew, ask, recall)
        assert stopped.is_set()  # the other turn was cancelled, never left running
    else:
        report = await _run(records, crew, ask, recall)
        expected = TurnOutcome.FAILED if case == "unreadable-episode" else TurnOutcome.WRITTEN
        assert [turn.outcome for turn in report.turns] == [expected, TurnOutcome.WRITTEN]
    assert asyncio.all_tasks() - before == set()


async def test_a_second_stand_down_asks_only_the_agents_without_a_note(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    pair = (_member(), _member("data_analyst", "Rahda", "did:probos:x:rahda", "sov-data_analyst"))
    await _run(records, pair, ask)
    asked.clear()
    third = _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist")
    again = await _run(records, (*pair, third), ask)

    assert [turn.outcome for turn in again.turns] == [
        TurnOutcome.ALREADY_WRITTEN, TurnOutcome.ALREADY_WRITTEN, TurnOutcome.WRITTEN,
    ]
    assert asked == ["pathologist"]
    first_note = await records.read_entry(exit_note_path(_SHIP, "surgeon"), "captain")
    assert "revision" not in first_note["frontmatter"]  # never rewritten


@pytest.mark.parametrize("case", ["same-type", "same-member", "written-meanwhile"])
async def test_one_billet_gets_one_turn_and_no_note_is_ever_replaced(tmp_path: Path, case: str) -> None:
    """A2 (M2-3): two crew agents of one agent type share their billet's path (register R9). The first in crew order
    takes the turn and the second is not asked. A member listed twice is asked once. A note written by anyone after
    the stand-down began is found under the write lock and kept."""
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []
    path = exit_note_path(_SHIP, "surgeon")

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_id)
        if case == "written-meanwhile":
            await records.write_entry(
                author="Bones", path=path, content="Written by hand meanwhile.", message="test: meanwhile",
                classification="ship",
            )
        return _reply()

    first = _member()
    second = CrewMember("slot-second", "surgeon", "sov-second", "did:probos:x:selar", "Selar")
    crew = {"same-type": (first, second), "same-member": (first, first), "written-meanwhile": (first,)}[case]
    report = await _run(records, crew, ask, concurrency=1)

    note = await records.read_entry(path, "captain")
    if case == "written-meanwhile":
        assert [turn.outcome for turn in report.turns] == [TurnOutcome.ALREADY_WRITTEN]
        assert note["frontmatter"]["author"] == "Bones" and "revision" not in note["frontmatter"]
    else:
        assert [(turn.outcome, turn.path) for turn in report.turns] == [
            (TurnOutcome.WRITTEN, path), (TurnOutcome.DUPLICATE, path),
        ]
        assert asked == ["slot-surgeon"]
        assert note["frontmatter"]["author"] == "Chapel" and "revision" not in note["frontmatter"]


@pytest.mark.parametrize("fault", ["file", "directory", "entry-type"])
async def test_a_stand_down_that_cannot_read_a_written_note_asks_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """A2 (M1-F1 asked of the stand-down): a note already written that the OS refuses to read when the stand-down
    lists the notes. A skip would ask its author again and replace the note; the stand-down refuses instead. A4
    (M3-1): the same when the OS refuses to list the billet's directory, which the listing used to pass over. A5 (O4):
    the same when the OS cannot report the note's type."""
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    await _run(records, (_member(),), ask)
    asked.clear()
    path = exit_note_path(_SHIP, "surgeon")
    if fault == "file":
        _deny_reading(monkeypatch, records.repo_path / path)
    elif fault == "directory":
        _deny_listing(monkeypatch, (records.repo_path / path).parent)
    else:
        _deny_entry_type(monkeypatch, records.repo_path / path)
    with pytest.raises(StandDownRefused, match="Ship's Records could not be read"):
        await _run(records, (_member(),), ask)
    monkeypatch.undo()

    assert asked == []
    assert "revision" not in (await records.read_entry(path, "captain"))["frontmatter"]


async def test_a_billet_whose_note_cannot_be_checked_is_never_written_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A5 (7.3a's table, O7): ``Path.exists`` answers False for an error ``pathlib`` reads as "not there" (EBADF here;
    ELOOP, and on Windows "the device is not ready", among others), so a note written meanwhile was taken for none
    and revised. The check asks ``Path.lstat``: only a path that is not found is absent, and a check that cannot tell
    is the turn's ``failed``, with no path. Nothing is written, and the note stays as it was."""
    records = _records(_data_dir(tmp_path))
    path = exit_note_path(_SHIP, "surgeon")
    real_write, real_stat, real_lstat = records.write_entry, Path.stat, Path.lstat
    writes: list[str] = []
    bad = OSError(errno.EBADF, "bad file descriptor")

    def stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "surgeon.md":
            raise bad
        return real_stat(self, *args, **kwargs)

    def lstat(self: Path) -> Any:
        if self.name == "surgeon.md":
            raise bad
        return real_lstat(self)

    async def write_entry(**fields: Any) -> Any:
        writes.append(fields["path"])
        return await real_write(**fields)

    async def ask(member: CrewMember, prompt: str) -> str:
        await real_write(
            author="Bones", path=path, content="Written by hand meanwhile.", message="test: meanwhile",
            classification="ship",
        )
        monkeypatch.setattr(Path, "stat", stat)  # from here no check of the billet can be made
        monkeypatch.setattr(Path, "lstat", lstat)
        return _reply()

    records.write_entry = write_entry  # type: ignore[method-assign]
    report = await _run(records, (_member(),), ask)
    monkeypatch.undo()

    assert [(turn.outcome, turn.path) for turn in report.turns] == [(TurnOutcome.FAILED, "")]
    assert writes == []
    note = await records.read_entry(path, "captain")
    assert note["frontmatter"]["author"] == "Bones" and "revision" not in note["frontmatter"]


def test_the_prompt_says_writing_is_optional_and_what_the_note_is_for() -> None:
    prompt = exit_notes_prompt("Chapel", ("e1 2026-10-25: the coolant alarm cleared again",))

    for phrase in (
        "Captain to Chapel",
        "Your successor in this billet will not share your memories",
        "what you learned, what you would do differently, and what remains open",
        "Writing is optional",
        f"reply exactly {DECLINE_REPLY} and nothing is recorded",
        f"the four sections together at most {LESSON_MAX_CHARS} characters",
        *(f"## {name}\n" for name in LESSON_SECTIONS),
        "Cites: (optional)",
        "kept in Ship's Records under your callsign and DID",
        "The Captain may review them and veto them",
        "archived in the Ship's Archive at the reset, where every later crew can read them",
        "labelled as inherited from this crew",  # A2 (M2-9)
        "Reply with the notes alone, without using tools",
        "Write nothing you would not share with the whole ship",
        "do not quote your memories",
        "e1 2026-10-25: the coolant alarm cleared again",
    ):
        assert phrase in prompt, phrase


async def test_an_agent_without_an_identity_is_not_asked(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    crew = (_member(did=""), _member("pathologist", "", "did:probos:x:selar", "sov-pathologist"))
    report = await _run(records, crew, ask)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.NO_IDENTITY, TurnOutcome.NO_IDENTITY]
    assert asked == []
    assert await _notes(records) == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("callsign", "Chapel\n## Observation"), ("callsign", "C" * (EXIT_NOTE_CALLSIGN_MAX_CHARS + 1)),
        ("agent_type", "sur\x00geon"), ("did", "did:probos:x:\ud800"),
        ("callsign", "Chapel---Two"),  # A4 (R2-F3): Ship's Records would read it back as "Chapel"
    ],
    ids=["multiline-callsign", "long-callsign", "nul-agent-type", "surrogate-did", "delimiter-callsign"],
)
async def test_an_identity_that_cannot_stand_in_the_note_is_not_asked(tmp_path: Path, field: str, value: str) -> None:
    """A2 (M2-7): the promotion's own provenance check, before the turn. An identity whose note the promotion would
    withhold (a line break or NUL in the origin line, a value past its bound, a DID SQLite cannot store) is never
    asked and never reported written."""
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    member = dataclasses.replace(_member(), **{field: value})
    report = await _run(records, (member,), ask)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.NO_IDENTITY]
    assert asked == []
    assert await _notes(records) == []


# --- S11 to S14: the vessel, the console, and what it never touches ------------------------------------------------


@pytest.mark.parametrize("case", ["archive-disabled", "no-records", "no-instance-id", "unknown-instance-id"])
async def test_the_stand_down_refuses_when_nothing_could_be_kept_or_attributed(tmp_path: Path, case: str) -> None:
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path, archive_enabled=case != "archive-disabled")
    records = None if case == "no-records" else _records(data_dir)
    instance_id = {"no-instance-id": "", "unknown-instance-id": "unknown"}.get(case, _SHIP)
    runtime, received = _vessel(
        config, records, MockEpisodicMemory(), replies={"surgeon": ("Chapel", _reply())}, instance_id=instance_id,
    )

    refusal = {
        "archive-disabled": "Ship's Archive is disabled", "no-records": "Ship's Records is not running",
        "no-instance-id": "has no instance id", "unknown-instance-id": "has no instance id",
    }[case]
    with pytest.raises(StandDownRefused, match=refusal):  # each case's own refusal, never another's (A1)
        await stand_down_vessel(runtime)

    assert received == []  # nobody was asked


@pytest.mark.parametrize(
    "bounds", [{"turn_seconds": 0.0}, {"window_seconds": -1.0}, {"concurrency": 0}], ids=["turn", "window", "concurrency"],
)
async def test_a_bound_that_is_not_positive_is_refused_before_anything_is_read(
    tmp_path: Path, bounds: dict[str, Any],
) -> None:
    """A4 (round 2, M2's record): a bound that is not positive is a caller's error, refused before Ship's Records is
    read and before anyone is asked. The wait bounds the test: a stand-down with no turn slot would never end."""
    records = _records(_data_dir(tmp_path))
    real_list, asked, listed = records.list_entries, [], []

    async def list_entries(*args: Any, **kwargs: Any) -> Any:
        listed.append(args)
        return await real_list(*args, **kwargs)

    records.list_entries = list_entries  # type: ignore[method-assign]

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    with pytest.raises(ValueError, match="bounds must be positive"):
        await asyncio.wait_for(_run(records, (_member(),), ask, **bounds), timeout=5.0)
    assert (asked, listed) == ([], [])


async def test_the_vessel_stand_down_sends_each_crew_agent_the_captains_message_through_the_intent_bus(
    tmp_path: Path,
) -> None:
    data_dir = _data_dir(tmp_path)
    memory = MockEpisodicMemory()
    for episode in _episodes(2, "sov-surgeon"):
        await memory.store(episode)
    runtime, received = _vessel(
        _config(tmp_path), _records(data_dir), memory,
        replies={"surgeon": ("Chapel", _reply("e1")), "data_analyst": ("Rahda", None)},
    )

    report = await stand_down_vessel(runtime)

    assert [(turn.agent_type, turn.outcome) for turn in report.turns] == [
        ("data_analyst", TurnOutcome.NO_REPLY), ("surgeon", TurnOutcome.WRITTEN),
    ]  # the utility agent is not crew and has no turn
    assert sorted(intent.target_agent_id for intent in received) == ["slot-data_analyst", "slot-surgeon"]
    for intent in received:
        assert intent.intent == "direct_message"
        assert (intent.params["from"], intent.params["session"]) == ("captain", False)
        assert intent.params[BOUNDED_TURN_PARAM] is True  # A2 (M2-1): the DM consumer answers it inline, single-pass
        assert intent.ttl_seconds == STAND_DOWN_TURN_SECONDS
        assert "Writing is optional" in intent.params["text"]
    note = await _records(data_dir).read_entry(report.turns[1].path, "captain")
    assert note["frontmatter"][EXIT_NOTE_KEY]["author_did"] == f"did:probos:{_SHIP}:surgeon"
    assert note["frontmatter"][EXIT_NOTE_KEY]["source_episode_ids"] == ["ep-001"]  # e1: the most recent episode
    assert await _notes(_records(data_dir)) == [exit_note_path(_SHIP, "surgeon")]


async def test_only_the_console_runs_a_stand_down(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "/stand-down" in ProbOSShell.COMMANDS
    called: list[str] = []

    async def _recorded(runtime: Any, console: Any, arg: str) -> None:
        called.append(arg)

    monkeypatch.setattr(commands_stand_down, "cmd_stand_down", _recorded)
    shell = ProbOSShell.__new__(ProbOSShell)
    shell.runtime, shell.console, shell.renderer = MagicMock(), MagicMock(), MagicMock()

    await shell._dispatch_slash("/stand-down")

    assert called == [""]
    runtime = MagicMock()
    answer = await _handle_slash_command("/stand-down", runtime)
    assert "only available in the CLI terminal" in answer["response"]
    assert runtime.mock_calls == []  # the HXI chat and the channels reach nothing on the vessel


async def test_the_console_command_reports_each_turn_and_the_next_steps(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    runtime, _received = _vessel(  # A2 (M2-9): a callsign that is Rich markup is printed as text
        _config(tmp_path), _records(data_dir), MockEpisodicMemory(),
        replies={"surgeon": ("[bold]Chapel[/bold]", _reply())},
    )
    output = StringIO()

    await commands_stand_down.cmd_stand_down(runtime, Console(file=output, width=200), "")

    text = output.getvalue()
    assert f"[bold]Chapel[/bold]: written -> {exit_note_path(_SHIP, 'surgeon')}" in text
    assert "probos archive pending" in text and "probos archive veto PATH --reason TEXT" in text
    runtime.config.archive.enabled = False
    refused = StringIO()
    await commands_stand_down.cmd_stand_down(runtime, Console(file=refused, width=200), "")
    assert "Stand-down refused" in refused.getvalue()


async def test_the_console_counts_completed_writes_and_names_a_note_a_failed_write_may_have_left(
    tmp_path: Path,
) -> None:
    """A5 (round 3 M2-2): a write that published its note and then failed is not a completed write, but the next
    reset would archive the note unless the Captain vetoes it. The footer counts completed writes, and says apart how
    many writes did not complete but may have left a document at the path shown."""
    records = _records(_data_dir(tmp_path))
    real_write = records.write_entry

    async def write_entry(**fields: Any) -> Any:
        await real_write(**fields)  # published
        raise subprocess.TimeoutExpired(["git", "add"], 30)

    records.write_entry = write_entry  # type: ignore[method-assign]
    runtime, _received = _vessel(
        _config(tmp_path), records, MockEpisodicMemory(), replies={"surgeon": ("Chapel", _reply())},
    )
    output = StringIO()

    await commands_stand_down.cmd_stand_down(runtime, Console(file=output, width=200), "")

    text = output.getvalue()
    assert f"Chapel: failed -> {exit_note_path(_SHIP, 'surgeon')}" in text
    assert "0 exit note(s) written" in text
    assert "1 write(s) did not complete and may have left a document at the path shown" in text
    assert len((await plan_promotion(records, timeline_id=_SHIP)).records) == 1  # premise: the reset would archive it


async def test_the_console_command_takes_no_arguments() -> None:
    """A4 (round 2, M2's record): ``/stand-down`` takes no arguments; with one it prints its usage and touches nothing."""
    runtime, output = MagicMock(), StringIO()

    await commands_stand_down.cmd_stand_down(runtime, Console(file=output, width=200), "now")

    assert "Usage: /stand-down  (no arguments)" in output.getvalue()
    assert runtime.mock_calls == []  # nobody asked, nothing read


def test_the_stand_down_never_writes_the_ship_s_archive() -> None:
    tree = ast.parse((_SRC / "stand_down.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {  # A2 (M2-9): ``from probos.knowledge import archive_store`` names the module through its alias
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module for alias in node.names
    }
    called = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert not any(name.startswith("probos.knowledge.archive") for name in imported)
    assert called.isdisjoint({"promote_entry", "veto_source", "erase_entry", "record_generation"})


# --- S15: the real seam ----------------------------------------------------------------------------------------------


async def _remember_and_stand_down(runtime: Any, memory: MockEpisodicMemory) -> Any:
    for episode in _episodes(2, "sov-surgeon"):
        await memory.store(episode)
    return await stand_down_vessel(runtime)


async def _erase_the_cited_episode(tmp_path: Path, memory: MockEpisodicMemory, episode_id: str) -> tuple[int, ...]:
    store = _archive_store(tmp_path)  # the next generation's vessel opens the same archive
    await store.initialize()
    try:
        with pytest.raises(ArchiveCitationsBlockErasure) as refused:
            await ErasureManager(memory, None, None, archive_store=store).forget_episode(episode_id)
        return refused.value.entry_ids
    finally:
        await store.close()


def test_a_stand_down_note_reaches_a_later_crew_as_inherited_and_its_citation_reaches_the_erasure_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    memory = MockEpisodicMemory()
    runtime, _received = _vessel(config, _records(data_dir), memory, replies={"surgeon": ("Chapel", _reply("e1"))})

    report = asyncio.run(_remember_and_stand_down(runtime, memory))
    path = report.turns[0].path
    assert report.turns[0].outcome is TurnOutcome.WRITTEN

    assert _reset(monkeypatch, config, data_dir) == 0  # the real probos reset promotes before it wipes
    archive = tmp_path / "archive.db"
    ((entry_id, kind, timeline, did, cited),) = _rows(
        archive, "SELECT id, source_kind, timeline_id, author_did, source_episode_ids FROM archive WHERE source_ref = ?",
        (path,),
    )
    assert (kind, timeline, did, json.loads(cited)) == ("exit_note", _SHIP, f"did:probos:{_SHIP}:surgeon", ["ep-001"])

    results = asyncio.run(_oracle_query(tmp_path, "coolant drift alarm"))  # a later crew's real Oracle
    inherited = [result for result in results if "Exit notes left by Chapel" in result.content]
    assert len(inherited) == 1
    assert inherited[0].content.splitlines()[0] == "[Inherited from the crew of generation 1: not your own memory]"

    # Here the cited episode outlives the reset (this memory is not the reset's data directory). S3's check refuses its
    # erasure, which is the citation S5's continuous promotion will rely on while episodes are still live.
    assert asyncio.run(_erase_the_cited_episode(tmp_path, memory, "ep-001")) == (entry_id,)


# --- S16: the real DM consumer (A2, M2-1) ----------------------------------------------------------------------------


async def test_a_stand_down_turn_is_answered_inline_by_the_real_dm_consumer_and_never_promoted(tmp_path: Path) -> None:
    """A2 (M2-1), the real seam: real ``CognitiveAgent`` DM consumers (``perceive``, then the conversational agentic
    gate the agent's decision step calls) with the shipped ``dm_agentic`` settings armed: the tool-calling loop on, and
    promotion into a background work item after 40 s. The stand-down's turns take the single-pass path: the loop's
    model is never called, no work item is opened and no promoted task is left. The control: the same agent's ordinary
    1:1 message still runs the loop."""
    runtime, received = _vessel(
        _config(tmp_path), _records(_data_dir(tmp_path)), MockEpisodicMemory(),
        replies={"surgeon": ("Chapel", None), "data_analyst": ("Rahda", None)},
    )
    runtime.config.dm_agentic.enabled = True  # the shipped settings (config/system.yaml, dm_agentic)
    runtime.config.dm_agentic.promote_to_task_after_seconds = 40.0
    work = WorkItemStore(db_path=str(tmp_path / "work.db"))
    await work.start()
    runtime.work_item_store = work
    runtime.chat_thread_store = ChatThreadStore(tmp_path / "threads.db")
    runtime.trust_network = TrustNetwork()
    runtime.ontology.get_agent_department = lambda agent_type: "medical"
    loop_requests: list[Any] = []
    single_pass: list[str] = []

    class OfflineModel(BaseLLMClient):
        """The only stand-in: the model behind the tool-calling loop answers at once, and is counted."""

        async def complete(self, request: Any, *, priority: Any = None) -> LLMResponse:
            loop_requests.append(request)
            return LLMResponse(
                content=_reply(), model="offline-stub", tier=request.tier, tokens_used=1, request_id=request.id,
            )

    members = crew_for_stand_down(runtime)
    runtime.registry = AgentRegistry()
    agents: list[CognitiveAgent] = []
    for member in members:
        agent = CognitiveAgent(
            agent_id=member.agent_id, instructions="Offline only.", runtime=runtime, llm_client=OfflineModel(),
        )
        agent.agent_type, agent.callsign = member.agent_type, member.callsign
        await runtime.registry.register(agent)
        agents.append(agent)

        async def consumer(intent: IntentMessage, agent: CognitiveAgent = agent) -> IntentResult:
            received.append(intent)
            observation = await agent.perceive(intent)
            text = await agent._maybe_run_conversational_agentic(  # the gate the decision step calls first
                observation, system_prompt="Offline only.",
                user_message=CognitiveAgent._format_direct_message_trigger(intent.params),
            )
            if text is None:  # the single-pass path answers inline; the stub stands for its one model call
                single_pass.append(intent.target_agent_id)
                text = _reply()
            return IntentResult(intent_id=intent.id, agent_id=agent.id, success=True, result=text, confidence=1.0)

        runtime.intent_bus.subscribe(member.agent_id, consumer, intent_names=["direct_message"])
    try:
        report = await stand_down_vessel(runtime)
        turns, items, during = list(received), await work.list_work_items(), len(loop_requests)
        control = await runtime.intent_bus.send(IntentMessage(
            intent="direct_message", params={"text": "How was the watch?", "from": "captain", "session": False},
            target_agent_id=members[0].agent_id, ttl_seconds=60.0,
        ))
    finally:
        for agent in agents:
            while agent._promoted_turn_tasks:
                await asyncio.gather(*tuple(agent._promoted_turn_tasks), return_exceptions=True)
        await work.stop()

    assert len(turns) == 2 and all(intent.params[BOUNDED_TURN_PARAM] is True for intent in turns)
    assert report.count(TurnOutcome.WRITTEN) == 2
    assert sorted(single_pass) == sorted(member.agent_id for member in members)  # each answered inline
    assert during == 0  # the tool-calling loop never ran for a stand-down turn
    assert items == []  # and nothing was promoted into a work item
    assert all(not agent._promoted_turn_tasks for agent in agents)
    assert control is not None and control.success
    assert len(loop_requests) > during  # the control: an ordinary 1:1 message still runs the loop
```

### 7.11 `src/probos/knowledge/erasure.py` (M3)

Pair 1 (import):

SEARCH:
```python
from collections.abc import AsyncIterator, Callable
```
REPLACE:
```python
from collections.abc import AsyncIterator, Callable, Mapping
```

Pair 2 (the refusal and its check, before `ErasureManager`):

SEARCH:
```python
class ErasureManager:
    def __init__(
        self,
        episodic_memory: Any | None,
```
REPLACE:
```python
class ExitNotesBlockErasure(Exception):
    """AD-1341 S4 (D14): exit notes the next reset would archive cite episodes this erasure would erase; none erased.

    ``paths`` are those notes' Ship's Records paths. The Captain vetoes each with ``probos archive veto PATH --reason
    TEXT``, so it is never archived, and retries. Ship's Records are the crew's documents, so this path never edits a
    note. The message carries the count only.
    """

    def __init__(self, paths: tuple[str, ...]) -> None:
        super().__init__(f"exit_notes_cite_erased_episodes:count={len(paths)}")
        self.paths = paths


def _refuse_while_an_exit_note_cites(citations: Mapping[str, tuple[str, ...]] | None, episode_ids: list[str]) -> None:
    """AD-1341 S4 (D14): raise ``ExitNotesBlockErasure`` before anything is erased if a pending exit note cites one.

    ``citations`` (episode id -> the notes citing it) is read once per request, before the manager is built
    (``archive_promotion.exit_note_citations``); None checks nothing. A module function, so ``ErasureManager`` stays
    within its 15-method SRP trigger.
    """
    if not citations or not episode_ids:
        return
    paths = tuple(sorted({path for episode_id in episode_ids for path in citations.get(episode_id, ())}))
    if paths:
        raise ExitNotesBlockErasure(paths)


class ErasureManager:
    def __init__(
        self,
        episodic_memory: Any | None,
```

Pair 3 (the manager takes the citations; **S3 anchor**):

SEARCH:
```python
        archive_store: ArchiveStore | None = None,
    ) -> None:
```
REPLACE:
```python
        archive_store: ArchiveStore | None = None,
        exit_note_citations: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
```

Pair 4 (kept on the manager):

SEARCH:
```python
        self._audit_log = audit_log
```
REPLACE:
```python
        self._audit_log = audit_log
        # AD-1341 S4: episode id -> the exit notes awaiting promotion that cite it, read once by the route; None checks nothing
        self._exit_note_citations = exit_note_citations
```

Pair 5 (one episode: checked before its attachments):

SEARCH:
```python
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        unlinked = await self._delete_attachments(attachment_ids)
```
REPLACE:
```python
        _refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])  # AD-1341 S4: before anything is erased
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        unlinked = await self._delete_attachments(attachment_ids)
```

Pair 6 (a scan's matches: checked before the first erase):

SEARCH:
```python
        """Erase each episode in turn; raise ``ErasureCascadeIncomplete`` if the scan or any erase failed."""
        total_count = 0
```
REPLACE:
```python
        """Erase each episode in turn; raise ``ErasureCascadeIncomplete`` if the scan or any erase failed."""
        _refuse_while_an_exit_note_cites(self._exit_note_citations, episode_ids)  # AD-1341 S4: a scan's matches, first
        total_count = 0
```

### 7.12 `src/probos/routers/security.py` (M3)

Pair 1 (import, in order):

SEARCH:
```python
from probos.credential_store import crew_scope_token
```
REPLACE:
```python
from probos.credential_store import crew_scope_token
from probos.knowledge.archive_promotion import exit_note_citations
```

Pair 2 (imports, in order):

SEARCH:
```python
from probos.routers.auth import require_crew_scope
```
REPLACE:
```python
from probos.knowledge.erasure import ExitNotesBlockErasure
from probos.knowledge.records_store import RecordsStore
from probos.routers.auth import require_crew_scope
```

Pair 3 (the read, before the route):

SEARCH:
```python
@router.post("/forget")
async def request_erasure(
```
REPLACE:
```python
async def _pending_exit_note_citations(runtime: Any, archive: Any) -> dict[str, tuple[str, ...]] | None:
    """AD-1341 S4 (D14, D16): which episodes the exit notes the next reset would archive cite; None checks nothing.

    Only a real Ship's Records store is read (a runtime double's attribute is none), and only while the archive is
    enabled: a disabled archive promotes nothing. An enabled archive that is not open (failed at boot, or closed) is
    still checked, with every valid note counted, because the next reset opens the archive and would promote them
    (S3 register R2, for notes). A failed read propagates, so nothing is erased.
    """
    records = getattr(runtime, "records_store", None)
    section = getattr(getattr(runtime, "config", None), "archive", None)
    if not isinstance(records, RecordsStore) or getattr(section, "enabled", False) is not True:
        return None
    return await exit_note_citations(records, archive if isinstance(archive, ArchiveStore) else None)


@router.post("/forget")
async def request_erasure(
```

Pair 4 (read once, before anything is erased):

SEARCH:
```python
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
```
REPLACE:
```python
    citations = await _pending_exit_note_citations(runtime, archive)  # AD-1341 S4 (D14): once, before any erase
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
```

Pair 5 (the citations reach the manager):

SEARCH:
```python
        audit_log=_get_audit_log(runtime),
```
REPLACE:
```python
        audit_log=_get_audit_log(runtime),
        exit_note_citations=citations,  # AD-1341 S4 (D14): the pending notes' citations
```

Pair 6 (the refusal's answer; **S3 anchor**):

SEARCH:
```python
    except ArchiveCitationsBlockErasure as exc:  # AD-1341 S3 (D8): nothing was erased
```
REPLACE:
```python
    except ExitNotesBlockErasure as exc:  # AD-1341 S4 (D14): nothing was erased
        logger.warning(
            "AD-1341 S4: an AD-754 erasure was refused: %d exit note(s) awaiting promotion cite its episodes",
            len(exc.paths),
        )
        return JSONResponse(
            {
                "error": "exit_notes_cite_erased_episodes",
                "exit_note_paths": list(exc.paths),
                "next": "probos archive veto PATH --reason TEXT for each, then retry",
            },
            status_code=409,
        )
    except ArchiveCitationsBlockErasure as exc:  # AD-1341 S3 (D8): nothing was erased
```

### 7.13 New file: `tests/test_ad1341_s4_exit_note_erasure.py` (M3)

```python
"""AD-1341 S4 M3 (#1569): an AD-754 erasure erases nothing while an exit note the next reset would archive cites its
episodes, and the Captain's veto of the note clears the way.

A real ``EpisodicMemory`` (``test_ad1340_s1_eviction``'s rig), the real ``ErasureManager``, notes written by the real
stand-down service (``run_stand_down``; its agent's turn is a stub), the real citation read, the real ``ArchiveStore``,
the real app's ``POST /api/security/forget`` (S2a's client), the Captain's real ``probos archive veto`` (S3's
``_veto``) and the real ``probos reset`` (S1's ``_reset``).
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

import probos
from probos.api import create_app
from probos.knowledge.archive_promotion import exit_note_citations, plan_promotion
from probos.knowledge.archive_store import PromotionOutcome, SourceKind, VetoOutcome
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager, ExitNotesBlockErasure
from probos.routers import security
from probos.stand_down import CrewMember, TurnOutcome, run_stand_down
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _config, _data_dir, _records, _reset
from tests.test_ad1341_s3_erasure_cascade import _traced, _traces
from tests.test_ad1341_s3_review_cli import _veto
from tests.test_ad1341_s4_lessons import _deny_entry_type, _deny_listing, _deny_reading
from tests.test_ad1341_s4_stand_down import _reply

_SRC = Path(probos.__file__).resolve().parent
_FORGET = "/api/security/forget"
_CITED, _OTHER = "ep-000", "ep-001"
_RESOURCE = "/srv/reactor.log"
_TARGETS: dict[str, dict[str, str]] = {
    "episode": {"episode_id": _CITED},
    "agent": {"agent_id": "agent-a"},
    "resource": {"resource_path": _RESOURCE},
}
_MATCHED = {"episode": [_CITED], "agent": [_CITED, _OTHER], "resource": [_CITED]}  # of the two stored episodes
_AGENT = CrewMember(
    agent_id="slot-surgeon", agent_type="surgeon", sovereign_id="agent-a", did=f"did:probos:{_SHIP}:agent-a",
    callsign="Chapel",
)
_SECOND = CrewMember(  # A2: a second billet, so two notes can cite one episode
    agent_id="slot-pathologist", agent_type="pathologist", sovereign_id="agent-a",
    did=f"did:probos:{_SHIP}:pathologist", callsign="Selar",
)


def _episodes() -> list[Any]:
    """Two episodes of agent-a; only the first names the resource."""
    cited = dataclasses.replace(_episode(0), user_input=f"alpha section filed the coolant readings under {_RESOURCE}")
    return [cited, _episode(1)]


async def _stored(em: Any) -> None:
    for episode in _episodes():
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
    assert _live(em) == [_CITED, _OTHER]  # premise: both are live


def _live(em: Any) -> list[str]:
    return sorted(_raw(em, [_CITED, _OTHER])["ids"])


async def _stand_down(records: Any, *, cites: str = "e1", shown: int = 0, agent: CrewMember = _AGENT) -> str:
    """A real stand-down in which ``agent`` is shown one of agent-a's episodes (``_CITED`` by default) as e1."""

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply(cites)

    async def recall(member: CrewMember) -> list[Any]:
        return [_episodes()[shown]]

    report = await run_stand_down((agent,), ask=ask, recall=recall, records=records, timeline_id=_SHIP)
    assert [turn.outcome for turn in report.turns] == [TurnOutcome.WRITTEN]  # premise
    return report.turns[0].path


def _manager(
    memory: Any, citations: Any, archive: Any = None, attachments: Any = None, audit: Any = None,
) -> ErasureManager:
    options = {"exit_note_citations": citations, "archive_store": archive}  # the keywords, passed as a mapping
    return ErasureManager(memory, attachments, audit, **options)


async def _forget(manager: ErasureManager, target: str) -> Any:
    if target == "episode":
        return await manager.forget_episode(_CITED)
    if target == "agent":
        return await manager.forget_agent_memory("agent-a")
    return await manager.forget_resource(_RESOURCE)


# --- X1, X2: the refusal, and the Captain's way through it ---------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_erasure_a_pending_exit_note_cites_erases_nothing(tmp_path: Path, target: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        try:
            citations = await exit_note_citations(records, store)
            assert citations == {_CITED: (path,)}  # premise: the note cites the episode it was shown

            with pytest.raises(ExitNotesBlockErasure) as refused:
                await _forget(_manager(rig.em, citations, store), target)

            assert refused.value.paths == (path,)
            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased
        finally:
            await store.close()


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_a_refused_erasure_for_a_note_keeps_the_cited_episodes_attachment_and_audit_row(
    tmp_path: Path, target: str,
) -> None:
    """A1, S3's finding M3-F1 asked of this check: the refusal comes before every destructive consumer, the
    attachment's unlink and the audit marking included (S3's real attachment store and audit log, ``_traced``)."""
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    store = _store(tmp_path)
    await store.initialize()
    try:
        citations = await exit_note_citations(records, store)
        assert citations == {_CITED: (path,)}  # premise: the note cites the episode that holds the attachment
        async with _traced(tmp_path, store) as (rig, _archive_only, attachments, audit):
            with pytest.raises(ExitNotesBlockErasure) as refused:
                await _forget(_manager(rig.em, citations, store, attachments, audit), target)

            assert refused.value.paths == (path,)
            assert await _traces(rig.em, attachments, audit) == ([_CITED, _OTHER], True, [_CITED, _OTHER])
    finally:
        await store.close()


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_s3_s_archive_refusal_comes_before_this_slice_s_when_both_cite_the_episode(
    tmp_path: Path, target: str,
) -> None:
    """A2 (M3-F4): an archived note and a pending note both cite the target. S3's check runs first at every entry
    point, so the erasure is refused for the archive entry, and this slice's refusal is never reached."""
    records = _records(_data_dir(tmp_path))
    archived = await _stand_down(records)
    pending = await _stand_down(records, agent=_SECOND)
    store = _store(tmp_path)
    await store.initialize()
    try:
        plan = await plan_promotion(records, timeline_id=_SHIP)
        first = next(record for record in plan.records if record.source_ref == archived)
        assert await store.promote_entry(first) is PromotionOutcome.CREATED
        citations = await exit_note_citations(records, store)
        assert citations == {_CITED: (pending,)}  # premise: the archived note is S3's; the pending one is this slice's
        async with _memory(tmp_path / "vessel", "archive") as rig:
            await _stored(rig.em)
            with pytest.raises(ArchiveCitationsBlockErasure):
                await _forget(_manager(rig.em, citations, store), target)
            assert _live(rig.em) == [_CITED, _OTHER]
    finally:
        await store.close()


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, target: str,
) -> None:
    caplog.set_level(logging.WARNING)
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    records = _records(data_dir)
    path = await _stand_down(records)
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        try:
            runtime = _runtime(root, rig.em)
            runtime.records_store = records  # the runtime's public accessor
            runtime.archive_store = store  # S3's public accessor
            async with _client(runtime) as client:
                refused = await _post(client, _FORGET, _TARGETS[target])

                assert refused.status_code == 409, refused.text
                assert refused.json()["error"] == "exit_notes_cite_erased_episodes"
                assert refused.json()["exit_note_paths"] == [path]
                assert _live(rig.em) == [_CITED, _OTHER]
                refusals = [
                    record.getMessage() for record in caplog.records if "exit note(s)" in record.getMessage()
                ]
                assert refusals == [  # A2 (M3-F5): logged once, as a count: no path, episode id or note text
                    "AD-1341 S4: an AD-754 erasure was refused: 1 exit note(s) awaiting promotion cite its episodes",
                ]

                # The Captain's veto, as the CLI runs it: its own event loop, so in a thread.
                assert await asyncio.to_thread(_veto, monkeypatch, config, data_dir, path, "cites an erased episode") == 0

                erased = await _post(client, _FORGET, _TARGETS[target])

                assert erased.status_code == 200, erased.text
                assert sorted(erased.json()["deleted_episode_ids"]) == _MATCHED[target]
                assert _live(rig.em) == sorted({_CITED, _OTHER} - set(_MATCHED[target]))
        finally:
            await store.close()

    assert await asyncio.to_thread(_reset, monkeypatch, config, data_dir) == 0  # the real reset honours the veto
    assert _rows(tmp_path / "archive.db", "SELECT COUNT(*) FROM archive WHERE source_kind = 'exit_note'") == [(0,)]


# --- X3 to X5: what does not block, and what fails closed ----------------------------------------------------------


@pytest.mark.parametrize("state", ["vetoed", "erased", "present", "uncited", "another-episode"])
async def test_a_note_the_next_reset_would_not_archive_with_this_citation_blocks_nothing(
    tmp_path: Path, state: str,
) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(
        records, cites="" if state == "uncited" else "e1", shown=1 if state == "another-episode" else 0,
    )
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = (await plan_promotion(records, timeline_id=_SHIP)).records[0]
        if state == "vetoed":
            outcome = await store.veto_source(SourceKind.EXIT_NOTE, path, "not canon", timeline_id=_SHIP)
            assert outcome is VetoOutcome.RECORDED
        elif state in ("erased", "present"):
            assert await store.promote_entry(record) is PromotionOutcome.CREATED
            if state == "erased":
                entry_id = _rows(tmp_path / "archive.db", "SELECT id FROM archive")[0][0]
                assert await store.erase_entry(entry_id, "the Captain forgets it") is True
        citations = await exit_note_citations(records, store)
    finally:
        await store.close()
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        # Only this slice's check: an archived ("present") note is S3's check, its E1.
        result = await _manager(rig.em, citations).forget_episode(_CITED)

        assert result.deleted_episode_ids == [_CITED]
        assert _live(rig.em) == [_OTHER]


@pytest.mark.parametrize("archive", ["enabled-not-open", "disabled"])
async def test_the_check_fails_closed_while_the_archive_is_enabled_but_not_open(tmp_path: Path, archive: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        runtime.records_store = records
        runtime.archive_store = None  # failed at boot, or closed at shutdown
        runtime.config.archive.enabled = archive != "disabled"
        async with _client(runtime) as client:
            answer = await _post(client, _FORGET, {"episode_id": _CITED})

        if archive == "disabled":  # a disabled archive promotes nothing, so nothing is checked
            assert answer.status_code == 200, answer.text
            assert answer.json()["deleted_episode_ids"] == [_CITED]
        else:
            assert answer.status_code == 409, answer.text
            assert answer.json()["exit_note_paths"] == [path]
            assert _live(rig.em) == [_CITED, _OTHER]


async def test_the_forget_route_reads_notes_only_from_a_real_records_store(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    assert await exit_note_citations(records, None) == {_CITED: (path,)}  # premise: a real store's read would refuse
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)  # its records_store is a MagicMock attribute, as in every route test
        async with _client(runtime) as client:
            erased = await _post(client, _FORGET, {"episode_id": _CITED})

        assert erased.status_code == 200, erased.text
        assert erased.json()["deleted_episode_ids"] == [_CITED]


# --- X6, X7: authority, and the read's bound -----------------------------------------------------------------------


def _importers(name: str) -> set[str]:
    """The ``src`` files that import ``name`` from a module."""
    found: set[str] = set()
    for source in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == name for alias in node.names):
                found.add(source.relative_to(_SRC).as_posix())
    return found


def test_only_the_forget_route_reads_exit_note_citations_and_only_the_manager_refuses_on_them() -> None:
    raisers: set[str] = set()
    for source in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name) and node.exc.func.id == "ExitNotesBlockErasure"
            ):
                raisers.add(source.relative_to(_SRC).as_posix())

    assert _importers("exit_note_citations") == {"routers/security.py"}
    assert _importers("ExitNotesBlockErasure") == {"routers/security.py"}
    assert raisers == {"knowledge/erasure.py"}


async def test_a_note_written_after_the_request_read_its_citations_does_not_stop_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D14's disclosed bound (register R2), through the real route (A2, M3-F3). The route reads the pending notes'
    citations once, before it builds the manager. A note citing the episode that lands right after that read does
    not stop the request; a second read would have counted it."""
    records = _records(_data_dir(tmp_path))
    root = tmp_path / "vessel"
    reads: list[dict[str, tuple[str, ...]]] = []
    late: list[str] = []
    real_read = security.exit_note_citations

    async def read_then_a_late_note(store: Any, archive: Any) -> dict[str, tuple[str, ...]]:
        reads.append(await real_read(store, archive))
        if not late:
            late.append(await _stand_down(records))  # lands after the read, before the manager is built
        return reads[-1]

    monkeypatch.setattr(security, "exit_note_citations", read_then_a_late_note)
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        runtime.records_store = records
        runtime.archive_store = None
        runtime.config.archive.enabled = True
        async with _client(runtime) as client:
            answer = await _post(client, _FORGET, {"episode_id": _CITED})

        assert reads == [{}]  # one read per request, and it saw no note
        assert await real_read(records, None) == {_CITED: (late[0],)}  # premise: a second read would count it
        assert answer.status_code == 200, answer.text
        assert answer.json()["deleted_episode_ids"] == [_CITED]  # the disclosed bound: register R2


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
@pytest.mark.parametrize("fault", ["read", "listing", "entry-type"])
async def test_an_exit_note_the_route_cannot_read_now_refuses_the_erasure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, target: str,
) -> None:
    """A2 (M3-F1): a valid note citing the episode, which the OS refuses to read during the request. The route answers
    500 and erases nothing; once the note can be read, the refusal names it (the Captain's way through, unchanged).
    A5 (round 3 R3-M1-1, M3's coverage): the same through the route when the OS refuses to list the note's timeline
    directory (``[listing-*]``) or cannot report that directory's type (``[entry-type-*]``: the round-3 P1, in which
    the listing took the directory for a file, the read answered "no citations" and the erasure went ahead). The read
    runs before the manager is built (``routers/security.py``), so no attachment or audit row is touched (X1b).

    A3: the shared ``_client`` re-raises the app's exception (``raise_app_exceptions=True``), so this test builds a
    transport that answers as a served app does: Starlette's error middleware sends the 500, then re-raises, and the
    transport keeps the response. A wrapper records what the app raised, so the 500 is proved to be the denied read.
    """
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        runtime.records_store = records
        runtime.archive_store = None
        runtime.config.archive.enabled = True
        app = create_app(runtime)
        raised: list[Exception] = []

        async def served(scope: Any, receive: Any, send: Any) -> None:
            try:
                await app(scope, receive, send)
            except Exception as exc:
                raised.append(exc)
                raise

        transport = httpx.ASGITransport(app=served, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            note = records.repo_path / path
            if fault == "read":
                _deny_reading(monkeypatch, note)
            elif fault == "listing":
                _deny_listing(monkeypatch, note.parent)
            else:
                _deny_entry_type(monkeypatch, note.parent)
            failed = await _post(client, _FORGET, _TARGETS[target])
            assert failed.status_code == 500, failed.text
            assert failed.text == "Internal Server Error"  # what a served app sends: no path, no reason
            assert [type(exc) for exc in raised] == [PermissionError]  # the denied read, and nothing else
            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased
            monkeypatch.undo()
            refused = await _post(client, _FORGET, _TARGETS[target])

        assert len(raised) == 1  # the retry raised nothing
        assert refused.status_code == 409, refused.text
        assert refused.json()["exit_note_paths"] == [path]
```

## 8. Tracking (tracker pairs; M4's commit)

Written against the S3 oracle (`fefd7f79`) and re-verified on the S3 candidate `60e4415e` (A1). S3 merges first and adds its own head entries. The anchors below are the title line and the heading every entry so far has been inserted against, and S3's REPLACE keeps both. If the orchestrator's re-anchoring rule applies, keep these anchors. Set the date to the commit date.

**`PROGRESS.md`** (the new entry goes first, under the title):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1341 S4 (2026-10-26), #1569 slice 4 of 6 -- the lessons format, and the stand-down that gives each crew agent one bounded turn to leave exit notes for its successor.** A lesson has four sections, Observation, Discussion, Lesson and Recommendation (#1569 comment 1). One parser (`knowledge/lessons.py`) reads an agent's reply and the stored note, the four sections together at most 700 characters, so a whole archived note reaches a later crew in one Oracle tool entry; the format is closed under rendering, and the archive receives exactly the note the Captain reviewed. The Captain types `/stand-down` at the vessel's console (console only: the HXI chat and the channel adapters refuse it), and each crew agent gets one Captain's message through the intent bus, showing it up to 12 of its own recent episodes by handle. The message is a bounded turn: the agent answers it inline on its single-pass path, never through its tool-calling loop or a background work item. Writing is optional (`NO NOTES`). A turn is bounded at 180 s and the whole window at 900 s, with at most two turns at once; a late, failed or unreached turn writes nothing, and `probos reset` neither waits for nor needs a stand-down. A note is a Ship's Records document at `exit-notes/{timeline}/{agent_type}.md`: an origin line ("... A record, not a memory.") and the lesson, `ship` classification, and an `exit_note` envelope with the author's DID, callsign, agent type and the ids of the episodes it cites (only episodes it was shown; no episode text). A second stand-down asks only the agents without a note, and one stand-down gives each billet one turn. The window starts before Ship's Records is first read, and no write begins after it closes; the stand-down removes nothing, and a write that fails or is cut off after publishing is reported with its path; an AD-754 erasure fails closed on a note file that cannot be read. The reset's promotion archives each note as `SourceKind.EXIT_NOTE`, attributed to the timeline that wrote it, with the archive's first real `source_episode_ids`; a malformed note is withheld, never raised. The Captain reviews notes with `probos archive pending` and vetoes one with `probos archive veto PATH`. An AD-754 erasure (`POST /api/security/forget`) whose matched episodes a note awaiting promotion cites erases nothing and answers 409 `exit_notes_cite_erased_episodes` with the paths, and fails closed when the archive is enabled but not open; the Captain vetoes the note and retries. Chain-of-command review of lessons moves to S5. Open before S5 and not S4's: BF-939 (#1683, an erasure unlinks an attachment another episode shares) and an indexed citation read for S3's N+1 check. No schema, flag, config field, event type or API route. New: `src/probos/knowledge/lessons.py`, `src/probos/stand_down.py`, `src/probos/experience/commands/commands_stand_down.py`, `tests/test_ad1341_s4_lessons.py`, `tests/test_ad1341_s4_stand_down.py`, `tests/test_ad1341_s4_exit_note_erasure.py`. The contract is `prompts/ad-1341-s4-lessons-and-stand-down.md`.
```

**`DECISIONS.md`** (before the `### Explicit delegation models` heading, which every entry since 2026-10-17 has been inserted against):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1341 S4 -- The lessons format, and the stand-down that gives each crew agent one bounded turn to leave exit notes for its successor (2026-10-26, #1569 slice 4 of 6)

- *Scope.* Slice 4 of #1569 (Decision item 3, comment 1's format and the acceptance lines on the exit-notes window and on raw episodes), three code commits and one tracker commit. Files: `knowledge/lessons.py` (new), `knowledge/archive_store.py` (`SourceKind.EXIT_NOTE`), `knowledge/archive_promotion.py` (`_exit_note_record`, `exit_note_citations`), `stand_down.py` (new), `experience/commands/commands_stand_down.py` (new), `experience/shell.py`, `api.py`, `knowledge/erasure.py`, `routers/security.py` and three new tests. Contract: `prompts/ad-1341-s4-lessons-and-stand-down.md`.
- *D2-D5 (the stand-down).* `probos reset` runs with the vessel stopped, so the turn is a live step before it: `/stand-down` at the console, console only because the HXI chat and the channel adapters reach slash commands without the Captain's console. Each crew agent gets one Captain's `direct_message` through the intent bus, so its own cognition answers, marked `bounded_turn` so the agent answers inline on its single-pass path, never through the tool-calling loop or an AD-1165 background promotion (A2, 7.9a); a duty, agent work item or Ward Room thread cannot bound a window that ends at a reset. 180 s a turn, 900 s in all, two at once; a late, failed or unreached turn writes nothing. The bounds are constants.
- *D6-D11 (the note).* One parser for the reply and the stored note; four sections of at most 700 characters together, so a whole archived note fits one Oracle tool entry (A2); the format is closed under rendering, and the archive receives exactly the canonical note the Captain reviewed. A Ship's Records document at `exit-notes/{timeline}/{agent_type}.md` at `ship` classification, so S1's promotion and S3's review and veto handle it unchanged. Provenance from `IdentityService`; citations only of episodes the agent was shown; never episode text. The entry is attributed to the timeline that wrote the note. A note is never overwritten, so a second stand-down asks only the agents without one.
- *D12 (approval).* Opt-out review by the Captain, as S3 built it. Chain-of-command review (#1569 comment 1, item 3) moves to S5 with the after-action reports, because inside a bounded stand-down its reviewers are writing their own notes and an unfinished review would block or lose a note. The Captain may overrule this ordering.
- *D14, D16 (AD-754).* The erasure refuses while a note awaiting promotion cites a matched episode, read once per request with the promotion's own rule; the Captain vetoes the note and retries. Withholding at the reset through the eviction audit was rejected (best-effort writes, can be disabled). S3's R2 is decided fail-closed for notes. S3's R3 stays with S5, because S4 promotes only at the offline reset under the pidfile. S3's R11 (BF-939, #1683, shared attachment blobs) and R13 (an N+1 citation read) are scheduled before S5: S4's citations are notes read once per request, and its archived citations name episodes the same reset wipes.
- *Disclosed effects.* `SourceKind` gains `exit_note` (TEXT column; schema v1). The promotion plan, the dry run and `pending` list notes, and a malformed one is counted as withheld. `/forget` can answer 409 for notes, and 500 while a note file cannot be read. A stand-down spends at most one model turn per crew agent, and each agent records the exchange in its own episodic memory. `RecordsStore.list_entries` gains a keyword-only `strict` (default unchanged); a `direct_message` carrying `bounded_turn: True` is answered single-pass.
- *Reversal.* Revert the S4 commits. Notes stay in Ship's Records as ordinary documents that S1's criteria never promote. Archived exit-note entries stay and read as before (`source_kind` is text). `/stand-down` and the AD-754 refusal for notes go away.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M4's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the gate:** add a *Validation of record* bullet before AD-1341 S4's *Reversal* line: the campaign of record, its base tree, the sha256 of each §10 file and of the three new test files, and each row's first failing test. Add the same as a closing §16 of this contract, then regenerate the ledger.

**`docs/development/roadmap.md`:** no row; `AD-1341` does not appear there (S2 §8).

## 9. What this does NOT change

- `probos reset`: its flow, tiers, pidfile, refusals, exit codes, `--skip-promotion`, `--dry-run` lines and promotion message. Notes reach it only through `plan_promotion`.
- The archive's schema, idempotence key, `promote_entry`, `erase_entry`, vetoes, `generations`, S2's label and generation numbering, and the Oracle.
- S1's other criteria and C1; S3's review, veto and archive citation check; `ErasureManager`'s scans, attachments and cascade; `/forget`'s request model and 200 body; `/forget`'s missing authorization (S3 R1).
- AD-754's attachment ownership (BF-939, #1683; register R16) and S3's per-call archive citation read (S3 R13; register R17): both before S5.
- The cognitive chain, the proactive loop, the duty schedule, AD-1347, the intent bus and the identity registries. The DM path changes in one place (7.9a, A2): a `direct_message` with `bounded_turn: True` is not a conversational agentic turn. No other DM, sender or `dm_agentic` setting changes.
- The Oracle tool and its caps (`oracle_query_tool.py`), and every `RecordsStore.list_entries` caller but two (§5, A2).
- No new flag, `EventType`, API route, config field or `.db` file; `user_version` stays 1. `config/ontology/records.yaml` is not edited (register R10).
- Out of scope (D19): S5's after-action reports, continuous promotion and chain-of-command review; S6's `--full` snapshot, description entry and clean slate; fleet sharing; an HXI stand-down; lifting a veto; bulk vetoes.

## 10. Mutation rows (110 rows: 44 for M1, 50 for M2, 16 for M3; whole stripped lines, each occurring once in its file after §7)

One campaign on the assembled tree (M1 to M3 applied), after an unmutated baseline run of the three new test files that passes. Run each row against the named tests and restore the file before the next row. R-1 and R-2 mutate the same line, and so do R-3 and R-4, and E-1, E-5 and E-6; restore between them.

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| L-1 | M1 | `src/probos/knowledge/lessons.py` | `if tuple(name for name, _lines in sections) != LESSON_SECTIONS:` | `if False:` | `test_a_reply_not_in_the_format_is_no_lesson` |
| L-2 | M1 | `src/probos/knowledge/lessons.py` | `if any(not body for body in bodies) or sum(len(body) for body in bodies) > LESSON_MAX_CHARS:` | `if any(not body for body in bodies):` | `test_a_reply_not_in_the_format_is_no_lesson`, `test_a_whole_note_at_every_bound_reaches_a_later_crew_through_the_oracle_tool` |
| L-3 | M1 | `src/probos/knowledge/lessons.py` | `elif _CITES_LINE.match(line):` | `elif False:` | `test_the_four_sections_are_read_in_each_heading_form` |
| L-4 | M1 | `src/probos/knowledge/lessons.py` | `return not stripped or _DECLINED.match(stripped) is not None` | `return not stripped` | `test_a_declining_reply_is_recognised_and_nothing_else_is` |
| L-5 | M1 | `src/probos/knowledge/lessons.py` | `episode_id = offered.get(f"e{int(number)}")` | `episode_id = offered.get(f"e{int(number)}", f"e{int(number)}")` | `test_citations_name_only_the_episodes_offered` |
| L-6 | M1 | `src/probos/knowledge/lessons.py` | `if episode_id is not None and episode_id not in cited and len(cited) < LESSON_MAX_CITATIONS:` | `if episode_id is not None:` | `test_citations_name_only_the_episodes_offered`, `test_a_lesson_cites_at_most_the_bounded_number_of_episodes` |
| L-7 | M1 | `src/probos/knowledge/lessons.py` | `return f"{exit_notes_directory(timeline_id)}/{_slug(agent_type, 'agent_type')}.md"` | `return f"{EXIT_NOTES_DIR}/{_slug(agent_type, 'agent_type')}.md"` | `test_an_exit_note_has_one_path_per_timeline_and_agent_type` |
| L-8 | M1 | `src/probos/knowledge/lessons.py` | `if not slug:` | `if False:` | `test_an_exit_note_has_one_path_per_timeline_and_agent_type` |
| L-9 | M1 | `src/probos/knowledge/lessons.py` | `rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*:\s*{_EMPHASIS}\s*(.*)$", re.IGNORECASE,` | `rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*:?\s*{_EMPHASIS}\s*(.*)$", re.IGNORECASE,` | `test_a_rendered_lesson_parses_back_to_itself`, `test_the_four_sections_are_read_in_each_heading_form` |
| P-1 | M1 | `src/probos/knowledge/archive_promotion.py` | `return SourceKind.EXIT_NOTE  # AD-1341 S4: every exit note is a source; _exit_note_record withholds a bad one` | `return None` | `test_an_exit_note_is_promoted_with_its_own_provenance`, `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it` |
| P-2 | M1 | `src/probos/knowledge/archive_promotion.py` | `if path.startswith(f"{EXIT_NOTES_DIR}/"):  # AD-1341 S4: an exit note carries its own provenance` | `if False:` | `test_an_exit_note_is_promoted_with_its_own_provenance`, `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-3 | M1 | `src/probos/knowledge/archive_promotion.py` | `if type(version) is not int or version != EXIT_NOTE_VERSION:  # A2: True and 1.0 equal 1 and are not it` | `if version != EXIT_NOTE_VERSION:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-4 | M1 | `src/probos/knowledge/archive_promotion.py` | `if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):` | `if False:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-5 | M1 | `src/probos/knowledge/archive_promotion.py` | `if path != expected_path or frontmatter.get("author") != callsign:` | `if False:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-6 | M1 | `src/probos/knowledge/archive_promotion.py` | `if exit_note_lesson(callsign, agent_type, note_timeline, content) is None:` | `if False:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-7 | M1 | `src/probos/knowledge/archive_promotion.py` | `timeline_id=note_timeline,  # AD-1341 S4 (D9): the timeline that wrote the note, not the reset's` | `timeline_id=callsign,` | `test_an_exit_note_is_promoted_with_its_own_provenance` |
| P-8 | M1 | `src/probos/knowledge/archive_promotion.py` | `source_episode_ids=tuple(cited),  # AD-1341 S4: the agent's own episodes, by id; never their text` | `source_episode_ids=(),` | `test_an_exit_note_is_promoted_with_its_own_provenance`, `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it` |
| P-9 | M1 | `src/probos/knowledge/archive_promotion.py` | `author_did=author_did,` | `author_did="",` | `test_an_exit_note_is_promoted_with_its_own_provenance` |
| P-10 | M1 | `src/probos/knowledge/archive_promotion.py` | `if archive is not None and (await archive.source_state(record)).outcome is not PromotionOutcome.CREATED:` | `if False:` | `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it`, `test_a_veto_between_the_citation_read_and_the_promotion_decides_both` |
| P-11 | M1 | `src/probos/knowledge/archive_promotion.py` | `citing.setdefault(episode_id, []).append(path)` | `pass` | `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it`, `test_a_veto_between_the_citation_read_and_the_promotion_decides_both` |
| P-12 | M1 | `src/probos/knowledge/archive_promotion.py` | `if source_kind_for(path, listed["frontmatter"]) is not SourceKind.EXIT_NOTE:` | `if False:` | `test_a_document_the_promotion_skips_is_never_read_as_a_citing_note` |
| D-1 | M2 | `src/probos/stand_down.py` | `reply = await asyncio.wait_for(ask(member, prompt), timeout=remaining)` | `reply = await ask(member, prompt)` | `test_a_turn_that_runs_past_its_bound_is_cancelled_and_writes_nothing`, `test_the_window_bounds_a_turn_its_own_bound_would_allow` |
| D-2 | M2 | `src/probos/stand_down.py` | `if clock() > turn_deadline:  # a reply after the turn's deadline (never past the window) writes nothing` | `if False:` | `test_a_reply_that_returns_after_the_turn_s_deadline_writes_nothing`, `test_the_recall_and_the_ask_spend_one_turn[slow-recall]` (A4: S4's mutant is equivalent, since `_write`'s window check returns the same `TIMED_OUT`) |
| D-3 | M2 | `src/probos/stand_down.py` | `if clock() >= deadline:  # the window closed before this agent's turn began` | `if False:` | `test_the_window_closes_on_time_and_writes_nothing_late_or_unreached` |
| D-4 | M2 | `src/probos/stand_down.py` | `gate = asyncio.Semaphore(concurrency)` | `gate = asyncio.Semaphore(len(crew) + 1)` | `test_no_more_than_the_bounded_number_of_turns_run_at_once` |
| D-5 | M2 | `src/probos/stand_down.py` | `if path in existing:` | `if False:` | `test_a_second_stand_down_asks_only_the_agents_without_a_note` |
| D-6 | M2 | `src/probos/stand_down.py` | `cited = parse_citations(reply, offered)` | `cited = ()` | `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance`, `test_a_note_cites_only_episodes_the_agent_was_shown` |
| D-7 | M2 | `src/probos/stand_down.py` | `if is_declined(reply):` | `if False:` | `test_writing_is_optional_and_a_turn_that_leaves_no_lesson_writes_nothing` |
| D-8 | M2 | `src/probos/stand_down.py` | `classification="ship",  # AD-1341 S4 (D8): for the next crew, so ship-wide; C1 admits it to the archive` | `classification="department",` | `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance` |
| D-9 | M2 | `src/probos/stand_down.py` | `if not exit_note_provenance_ok(timeline_id, member.callsign, member.agent_type, member.did):` | `if False:` | `test_an_agent_without_an_identity_is_not_asked`, `test_an_identity_that_cannot_stand_in_the_note_is_not_asked` |
| D-10 | M2 | `src/probos/stand_down.py` | `if len(offered) >= STAND_DOWN_EPISODES:` | `if False:` | `test_a_note_cites_only_episodes_the_agent_was_shown` |
| D-11 | M2 | `src/probos/stand_down.py` | `if cost > EPISODE_EXCERPT_CHARS:` | `if False:` | `test_a_note_cites_only_episodes_the_agent_was_shown` |
| D-12 | M2 | `src/probos/stand_down.py` | `"source_episode_ids": list(cited),` | `"source_episode_ids": [],` | `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance` |
| D-13 | M2 | `src/probos/stand_down.py` | `if result is None or not result.success:  # refused, stopped or failed: no turn` | `if result is None:` | `test_the_vessel_stand_down_sends_each_crew_agent_the_captains_message_through_the_intent_bus` |
| D-14 | M2 | `src/probos/stand_down.py` | `if not runtime.config.archive.enabled:` | `if False:` | `test_the_stand_down_refuses_when_nothing_could_be_kept_or_attributed` |
| D-15 | M2 | `src/probos/stand_down.py` | `if not timeline_id or timeline_id == "unknown":  # the ontology's placeholder when no identity is loaded` | `if not timeline_id:` | `test_the_stand_down_refuses_when_nothing_could_be_kept_or_attributed` |
| D-16 | M2 | `src/probos/stand_down.py` | `if not is_crew_agent(agent, runtime.ontology):` | `if False:` | `test_the_vessel_stand_down_sends_each_crew_agent_the_captains_message_through_the_intent_bus` |
| D-17 | M2 | `src/probos/stand_down.py` | `write_lock = asyncio.Lock()  # one Ship's Records write at a time: the repository has one git index` | `write_lock = asyncio.Semaphore(concurrency)` | `test_the_stand_down_writes_one_note_at_a_time` |
| H-1 | M2 | `src/probos/experience/shell.py` | `"/stand-down": lambda: commands_stand_down.cmd_stand_down(rt, con, arg),` | `"/stand-down": lambda: commands_status.cmd_ping(rt, con, arg),` | `test_only_the_console_runs_a_stand_down` |
| A-1 | M2 | `src/probos/api.py` | `_BLOCKED_COMMANDS = {'/quit', '/debug', '/stand-down'}` | `_BLOCKED_COMMANDS = {'/quit', '/debug'}` | `test_only_the_console_runs_a_stand_down` |
| E-1 | M3 | `src/probos/knowledge/erasure.py` | `_refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])  # AD-1341 S4: before anything is erased` | `pass` | `test_an_erasure_a_pending_exit_note_cites_erases_nothing` |
| E-2 | M3 | `src/probos/knowledge/erasure.py` | `_refuse_while_an_exit_note_cites(self._exit_note_citations, episode_ids)  # AD-1341 S4: a scan's matches, first` | `pass` | `test_an_erasure_a_pending_exit_note_cites_erases_nothing` |
| E-3 | M3 | `src/probos/knowledge/erasure.py` | `if paths:` | `if False:` | `test_an_erasure_a_pending_exit_note_cites_erases_nothing` |
| E-4 | M3 | `src/probos/knowledge/erasure.py` | `self._exit_note_citations = exit_note_citations` | `self._exit_note_citations = None` | `test_an_erasure_a_pending_exit_note_cites_erases_nothing`, `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes` |
| E-5 | M3 | `src/probos/knowledge/erasure.py` | `_refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])  # AD-1341 S4: before anything is erased` (after E-1 is restored) | `await self._delete_attachments(await self._attachment_ids_for_episode(episode_id)); _refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])` | `test_a_refused_erasure_for_a_note_keeps_the_cited_episodes_attachment_and_audit_row[episode]` |
| E-6 | M3 | `src/probos/knowledge/erasure.py` | `_refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])  # AD-1341 S4: before anything is erased` (after E-5 is restored) | `await self._audit_log.mark_deleted(episode_id) if self._audit_log is not None else None; _refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])` | `test_a_refused_erasure_for_a_note_keeps_the_cited_episodes_attachment_and_audit_row[episode]` |
| R-1 | M3 | `src/probos/routers/security.py` | `return await exit_note_citations(records, archive if isinstance(archive, ArchiveStore) else None)` | `return None` | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes` |
| R-2 | M3 | `src/probos/routers/security.py` | `return await exit_note_citations(records, archive if isinstance(archive, ArchiveStore) else None)` (after R-1 is restored) | `return await exit_note_citations(records, None)` | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes` |
| R-3 | M3 | `src/probos/routers/security.py` | `if not isinstance(records, RecordsStore) or getattr(section, "enabled", False) is not True:` | `if getattr(section, "enabled", False) is not True:` | `test_the_forget_route_reads_notes_only_from_a_real_records_store` |
| R-4 | M3 | `src/probos/routers/security.py` | `if not isinstance(records, RecordsStore) or getattr(section, "enabled", False) is not True:` (after R-3 is restored) | `if not isinstance(records, RecordsStore):` | `test_the_check_fails_closed_while_the_archive_is_enabled_but_not_open` |
| R-5 | M3 | `src/probos/routers/security.py` | `exit_note_citations=citations,  # AD-1341 S4 (D14): the pending notes' citations` | `exit_note_citations=None,` | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes` |
| R-6 | M3 | `src/probos/routers/security.py` | `"exit_note_paths": list(exc.paths),` | `"exit_note_paths": [],` | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes` |
| L-10 | M1 | `src/probos/knowledge/lessons.py` | `if any(_heading(line) is not None or _CITES_LINE.match(line) for body in bodies for line in body.splitlines()):` | `if False:` | `test_every_lesson_the_parser_accepts_is_written_and_read_back_unchanged` |
| L-11 | M1 | `src/probos/knowledge/lessons.py` | `if type(text) is not str or _NOT_LESSON_TEXT.search(text) is not None:` | `if type(text) is not str:` | `test_a_reply_not_in_the_format_is_no_lesson`, `test_a_lesson_carries_no_control_character_but_tab_line_feed_and_carriage_return` |
| L-12 | M1 | `src/probos/knowledge/lessons.py` | `_DECLINED = re.compile(r"^[\W_]*no notes[\W_]*$", re.IGNORECASE)  # A2: _ is emphasis too (__NO NOTES__, _NO NOTES_)` | `_DECLINED = re.compile(r"^\W*no notes\W*$", re.IGNORECASE)` | `test_a_declining_reply_is_recognised_and_nothing_else_is` |
| L-13 | M1 | `src/probos/knowledge/lessons.py` | `type(value) is str and bool(value.strip()) and len(value) <= max_chars and _NOT_ONE_LINE.search(value) is None` | `type(value) is str and bool(value.strip()) and len(value) <= max_chars` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing`, `test_an_identity_that_cannot_stand_in_the_note_is_not_asked` |
| L-14 | M1 | `src/probos/knowledge/lessons.py` | the L-13 line (after L-13 is restored) | `type(value) is str and bool(value.strip()) and _NOT_ONE_LINE.search(value) is None` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing`, `test_an_identity_that_cannot_stand_in_the_note_is_not_asked` |
| L-15 | M1 | `src/probos/knowledge/lessons.py` | `if lesson is None or content != exit_note_body(callsign, agent_type, timeline_id, lesson):` | `if lesson is None:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-13 | M1 | `src/probos/knowledge/archive_promotion.py` | `if not exit_note_provenance_ok(*named):  # A2: one storable line each, within its bound` | `if not all(type(value) is str and value.strip() for value in named):` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-14 | M1 | `src/probos/knowledge/archive_promotion.py` | `for listed in await records.list_entries(EXIT_NOTES_DIR, strict=True):` | `for listed in await records.list_entries(EXIT_NOTES_DIR):` | `test_a_note_the_listing_cannot_read_now_is_never_read_as_no_citations`, `test_an_exit_note_the_route_cannot_read_now_refuses_the_erasure` |
| RS-1 | M1 | `src/probos/knowledge/records_store.py` | `raise  # AD-1341 S4 (A2): a file that exists but cannot be read now is never "no document"` | `pass` | `test_a_note_the_listing_cannot_read_now_is_never_read_as_no_citations`, `test_a_listed_note_the_strict_read_cannot_read_is_never_read_as_no_note`, `test_a_stand_down_that_cannot_read_a_written_note_asks_nobody[file]`, `test_an_exit_note_the_route_cannot_read_now_refuses_the_erasure[read-*]` |
| D-18 | M2 | `src/probos/stand_down.py` | `remaining = turn_deadline - clock()  # A2 (M2-5): what the recall spent is spent` | `remaining = min(turn_seconds, deadline - clock())` | `test_the_recall_and_the_ask_spend_one_turn[recall-runs-out]` |
| D-19 | M2 | `src/probos/stand_down.py` | the D-2 line (after D-2 is restored) | `if clock() > deadline:` | `test_a_reply_that_returns_after_the_turn_s_deadline_writes_nothing` |
| D-20 | M2 | `src/probos/stand_down.py` | `listed = await asyncio.wait_for(records.list_entries(directory, strict=True), timeout=window_seconds)` | `listed = await records.list_entries(directory, strict=True)` | `test_the_window_bounds_the_records_reads_and_writes_too[first-read]` |
| D-21 | M2 | `src/probos/stand_down.py` | the D-20 line (after D-20 is restored) | `listed = await asyncio.wait_for(records.list_entries(directory), timeout=window_seconds)` | `test_a_stand_down_that_cannot_read_a_written_note_asks_nobody` |
| D-22 | M2 | `src/probos/stand_down.py` | `await asyncio.wait_for(written, timeout=remaining)  # A2 (M2-2): the window cuts off an awaiting write` | `await written` | `test_the_window_bounds_the_records_reads_and_writes_too[write]` |
| D-23 | M2 | `src/probos/stand_down.py` | `if remaining <= 0:  # A2 (M2-2): the window closed while this turn waited for the write lock` | `if False:` | `test_the_window_bounds_the_records_reads_and_writes_too[write]` |
| D-24 | M2 | `src/probos/stand_down.py` | `if path in claimed_paths or member.agent_id in seen_agents:  # A2 (M2-3): one turn per billet, and per agent` | `if False:` | `test_one_billet_gets_one_turn_and_no_note_is_ever_replaced` |
| D-25 | M2 | `src/probos/stand_down.py` | `if present:  # A2 (M2-3), A4: a note written since the stand-down began; no await` | `if False:` | `test_one_billet_gets_one_turn_and_no_note_is_ever_replaced[written-meanwhile]` |
| D-37 | M2 | `src/probos/stand_down.py` | `return _turn_result(member, outcome, _left_at(path))  # A4: never removed; the report names it` | `return _turn_result(member, outcome)` | `test_a_write_that_fails_after_publishing_leaves_no_hidden_note[published]`, `[replaced]`, `test_on_the_real_clock_no_write_begins_after_the_window_and_every_note_left_is_reported[cut-off-after-publishing]` |
| D-38 | M2 | `src/probos/stand_down.py` | `remaining = deadline - clock()  # A4: after the check, so its time is charged to the window` | `remaining = window_seconds` | `test_the_window_bounds_the_records_reads_and_writes_too[write]`, `test_on_the_real_clock_no_write_begins_after_the_window_and_every_note_left_is_reported[the-check-outlasts-the-window]` |
| D-28 | M2 | `src/probos/stand_down.py` | `except (OverflowError, OSError, ValueError):  # A2 (M2-6): inf, or out of range; the turn still runs` | `except ():` | `test_one_member_s_fault_never_ends_the_other_turns_or_leaves_one_running[timestamps]` |
| D-29 | M2 | `src/probos/stand_down.py` | `except Exception:  # A2 (M2-6): one member's fault never ends the others' turns or the report` | `except ():` | `test_one_member_s_fault_never_ends_the_other_turns_or_leaves_one_running[unreadable-episode]` |
| D-30 | M2 | `src/probos/stand_down.py` | the D-9 line (after D-9 is restored) | `if not member.did.strip() or not member.callsign.strip():` | `test_an_identity_that_cannot_stand_in_the_note_is_not_asked` |
| D-31 | M2 | `src/probos/stand_down.py` | `cost += len(json.dumps(char)) - 2` | `cost += 1` | `test_the_captain_s_message_stays_inside_the_inline_params_bound_in_any_script[cjk]`, `[astral]` |
| D-32 | M2 | `src/probos/stand_down.py` | `turn.cancel()` | `pass` | `test_one_member_s_fault_never_ends_the_other_turns_or_leaves_one_running[self-cancelled]` |
| D-33 | M2 | `src/probos/stand_down.py` | `params={"text": text, "from": "captain", "session": False, BOUNDED_TURN_PARAM: True},  # A2 (M2-1)` | `params={"text": text, "from": "captain", "session": False},` | `test_the_vessel_stand_down_sends_each_crew_agent_the_captains_message_through_the_intent_bus`, `test_a_stand_down_turn_is_answered_inline_by_the_real_dm_consumer_and_never_promoted` |
| D-34 | M2 | `src/probos/stand_down.py` | the D-1 line (after D-1 is restored) | `reply = await asyncio.wait_for(ask(member, prompt), timeout=2 * remaining)` | `test_a_turn_that_runs_past_its_bound_is_cancelled_and_writes_nothing`, `test_the_window_bounds_a_turn_its_own_bound_would_allow` |
| D-35 | M2 | `src/probos/stand_down.py` | `from probos.dm_reply import DmReply` | `from probos.dm_reply import DmReply; from probos.knowledge import archive_store  # noqa: F401` | `test_the_stand_down_never_writes_the_ship_s_archive` |
| G-1 | M2 | `src/probos/cognitive/cognitive_agent.py` | `if params.get("bounded_turn") is True:  # AD-1341 S4 (A2): probos.stand_down.BOUNDED_TURN_PARAM` | `if False:` | `test_a_stand_down_turn_is_answered_inline_by_the_real_dm_consumer_and_never_promoted` |
| C-1 | M2 | `src/probos/experience/commands/commands_stand_down.py` | `console.print(f"  {escape(turn.callsign or turn.agent_type)}: {turn.outcome.value}{escape(where)}")` | `console.print(f"  {turn.callsign or turn.agent_type}: {turn.outcome.value}{escape(where)}")` | `test_the_console_command_reports_each_turn_and_the_next_steps` |
| E-7 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, [episode_id])  # AD-1341 S3: before anything is erased` | `_refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id]); await _refuse_while_the_archive_cites(self._archive_store, [episode_id])` | `test_s3_s_archive_refusal_comes_before_this_slice_s_when_both_cite_the_episode[episode]` |
| E-8 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: a resource's matches` | `_refuse_while_an_exit_note_cites(self._exit_note_citations, matching_ids); await _refuse_while_the_archive_cites(self._archive_store, matching_ids)` | `test_s3_s_archive_refusal_comes_before_this_slice_s_when_both_cite_the_episode[resource]` |
| R-7 | M3 | `src/probos/routers/security.py` | `"AD-1341 S4: an AD-754 erasure was refused: %d exit note(s) awaiting promotion cite its episodes",` | `"AD-1341 S4: an AD-754 erasure was refused: %d exit note(s) awaiting promotion cite its episodes " + str(exc.paths),` | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes` |
| R-8 | M3 | `src/probos/routers/security.py` | `citations = await _pending_exit_note_citations(runtime, archive)  # AD-1341 S4 (D14): once, before any erase` | `citations = [await _pending_exit_note_citations(runtime, archive) for _read in range(2)][-1]` | `test_a_note_written_after_the_request_read_its_citations_does_not_stop_it` |
| L-16 | M1 | `src/probos/knowledge/lessons.py` | `_NOT_LESSON_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")` | `_NOT_LESSON_TEXT = re.compile(r"[\x00\ud800-\udfff]")` | `test_a_reply_not_in_the_format_is_no_lesson[escape]`, `test_a_lesson_carries_no_control_character_but_tab_line_feed_and_carriage_return` |
| L-17 | M1 | `src/probos/knowledge/lessons.py` | `and _FRONTMATTER_DELIMITER not in value  # A4 (R2-F3): Ship's Records cuts a frontmatter value at "---"` | `and True` | `test_every_provenance_value_the_rule_admits_comes_back_whole_from_ship_s_records`, `test_an_identity_that_cannot_stand_in_the_note_is_not_asked[delimiter-callsign]`, `test_every_episode_offered_can_be_cited_by_a_note_the_promotion_archives[delimiter]` |
| L-18 | M1 | `src/probos/knowledge/lessons.py` | `_SECTION = f"((?a:{_SECTION_NAMES}))"` | `_SECTION = f"({_SECTION_NAMES})"` | `test_a_section_name_spelled_with_a_lookalike_letter_opens_no_section`, `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing[lookalike-heading]`, `test_a_note_the_rule_refuses_is_withheld_and_the_real_reset_still_runs` |
| P-15 | M1 | `src/probos/knowledge/archive_promotion.py` | `if type(cited) is not list or not all(is_exit_note_text(item, EXIT_NOTE_EPISODE_ID_MAX_CHARS) for item in cited):` | `if type(cited) is not list or not all(type(item) is str and item.strip() for item in cited):` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing[long-citation]`, `[newline-citation]` |
| RS-4 | M1 | `src/probos/knowledge/records_store.py` | `found = _markdown_files_or_raise(search_path) if strict else search_path.rglob("*.md")` | `found = search_path.rglob("*.md")` | `test_a_note_directory_the_listing_cannot_list_now_is_never_read_as_no_citations`, `test_a_stand_down_that_cannot_read_a_written_note_asks_nobody[directory]`, `[entry-type]`, `test_an_exit_note_the_route_cannot_read_now_refuses_the_erasure[listing-*]`, `[entry-type-*]` |
| RS-6 | M1 | `src/probos/knowledge/records_store.py` | `if strict:  # A5 (O5): a file the walk listed is never "no document", whatever the read's error` | `if strict and md_file.is_file():` | `test_a_listed_note_the_strict_read_cannot_read_is_never_read_as_no_note[*-stat-ebadf]` |
| RS-7 | M1 | `src/probos/knowledge/records_store.py` | `raise  # O2 (A5): a directory a listing reported is never "no documents"` | `return found` | `test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing[absent]`, `[not-a-directory]` |
| RS-8 | M1 | `src/probos/knowledge/records_store.py` | `return found  # O1: search_path does not exist, so nothing was written under it` | `raise` | `test_ship_s_records_without_exit_notes_cite_nothing`, `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance`, `test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing[absent]` |
| RS-9 | M1 | `src/probos/knowledge/records_store.py` | `if entry.is_dir(follow_symlinks=False):  # O4: an OSError propagates; it is never read as "a file"` | `if entry.is_dir():` | `test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing` (the clean trace) |
| RS-10 | M1 | `src/probos/knowledge/records_store.py` | `elif fnmatch.fnmatch(entry.name, "*.md"):` | `else:` | `test_the_strict_listing_lists_exactly_what_the_default_listing_lists[all]`, `[exit-notes]`, `test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing` |
| D-36 | M2 | `src/probos/stand_down.py` | `if not is_exit_note_text(episode_id, EXIT_NOTE_EPISODE_ID_MAX_CHARS) or episode_id in offered.values():` | `if type(episode_id) is not str or not episode_id.strip() or episode_id in offered.values():` | `test_every_episode_offered_can_be_cited_by_a_note_the_promotion_archives` |
| D-39 | M2 | `src/probos/stand_down.py` | `except Exception:  # log-and-degrade: the turn offers no episodes, so its note cites none` | `except ():` | `test_a_failed_episode_read_offers_none_and_the_note_cites_none`, `test_the_recall_and_the_ask_spend_one_turn[recall-runs-out]` |
| D-40 | M2 | `src/probos/stand_down.py` | `"labelled as inherited from this crew. Write nothing you would not share with the whole ship. Summarise in "` | `"Write nothing you would not share with the whole ship. Summarise in "` | `test_the_prompt_says_writing_is_optional_and_what_the_note_is_for` |
| D-41 | M2 | `src/probos/stand_down.py` | `if concurrency < 1 or turn_seconds <= 0 or window_seconds <= 0:` | `if False:` | `test_a_bound_that_is_not_positive_is_refused_before_anything_is_read` |
| C-2 | M2 | `src/probos/experience/commands/commands_stand_down.py` | `if arg.strip():` | `if False:` | `test_the_console_command_takes_no_arguments` |
| P-16 | M1 | `src/probos/knowledge/archive_promotion.py` | `if document is None and listed_readable:  # A5 (O6): listed a moment ago, not found now: never "no citations"` | `if False:` | `test_a_listed_note_the_citation_read_cannot_find_again_is_never_read_as_no_citations[ebadf]`, `[enoent]` |
| P-17 | M1 | `src/probos/knowledge/archive_promotion.py` | `except ValueError:  # A5 (R3-M1-2): an integer longer than Python's integer-string limit` | `except ():` | `test_a_stored_value_that_cannot_be_shown_as_text_never_stops_the_promotion`, `test_a_note_holding_a_value_that_cannot_be_shown_as_text_is_archived_by_the_real_reset` |
| P-18 | M1 | `src/probos/knowledge/archive_promotion.py` | `for candidate in (_stored_text(topic), path.rsplit("/", 1)[-1].removesuffix(".md")):` | `for candidate in (str(topic) if topic else "", path.rsplit("/", 1)[-1].removesuffix(".md")):` | `test_a_stored_value_that_cannot_be_shown_as_text_never_stops_the_promotion[finding-topic]` |
| P-19 | M1 | `src/probos/knowledge/archive_promotion.py` | `author_callsign=_stored_text(frontmatter.get("author")),` | `author_callsign=str(frontmatter.get("author") or ""),` | `test_a_stored_value_that_cannot_be_shown_as_text_never_stops_the_promotion[finding-author]` |
| D-42 | M2 | `src/probos/stand_down.py` | `present = _present(records.repo_path / path)  # A5: what Path.exists reads as "not there" is unknown here` | `present = False` | `test_one_billet_gets_one_turn_and_no_note_is_ever_replaced[written-meanwhile]`, `test_on_the_real_clock_no_write_begins_after_the_window_and_every_note_left_is_reported[the-check-outlasts-the-window]`, `test_a_billet_whose_note_cannot_be_checked_is_never_written_over` |
| D-43 | M2 | `src/probos/stand_down.py` | `return "" if _present(records.repo_path / path) is False else path` | `return path if _present(records.repo_path / path) else ""` | `test_a_failed_write_whose_note_cannot_be_checked_still_names_its_path` |
| D-44 | M2 | `src/probos/stand_down.py` | `if present is None:  # A5: whether a note is there cannot be told now, so nothing is written over it` | `if False:` | `test_a_billet_whose_note_cannot_be_checked_is_never_written_over` |
| D-45 | M2 | `src/probos/stand_down.py` | `if clock() >= deadline:  # A5 (round 3 M2-3): the first read returned after the window closed` | `if False:` | `test_a_first_read_that_returns_after_the_window_asks_nobody_and_starts_no_turn` |
| D-46 | M2 | `src/probos/stand_down.py` | `except (FileNotFoundError, NotADirectoryError):  # A5: nothing is there` | `except OSError:` | `test_a_billet_whose_note_cannot_be_checked_is_never_written_over`, `test_a_failed_write_whose_note_cannot_be_checked_still_names_its_path` |
| C-3 | M2 | `src/probos/experience/commands/commands_stand_down.py` | `if left:  # A5 (round 3 M2-2): a write that did not complete may still have published its note` | `if False:` | `test_the_console_counts_completed_writes_and_names_a_note_a_failed_write_may_have_left` |

The heading's count includes R-2 and R-4. A2: L-13 and L-14, D-1 and D-34, D-2 and D-19, D-9 and D-30, D-20 and D-21 each mutate one line; restore between them. A4: D-26 and D-27 are retired with the rollback they mutated (their numbers are not reused); D-22, D-25 and L-11 name their lines as A4 rewrote them; RS-2 and RS-3 mutate two lines of one helper; restore between them. A5: RS-2, RS-3 and RS-5 are retired with the `os.walk` lines they mutated (their numbers are not reused); D-25 names its line as A5 rewrote it; RS-7 and RS-8 mutate two lines of one `except` clause, so restore between them.

Rows with no mutation:

- `_offer`'s duplicate-id skip, and `_ask_and_write`'s write failure: no supported caller produces a duplicate id or a failing write in a test without injection. They are logged and covered by S1's and S2's outcomes.
- (A1) The stand-down's write lock now has a row, D-17: S6b holds each write open, so an unserialised second write overlaps it.
- P-3's `wrong-version` is also an envelope `version` the stand-down never writes.
- (A2) The stand-down's preflight (`exit_note_lesson(...) != lesson` in `_ask_and_write`): unreachable once the provenance check (D-9, D-30) and the format's closure (L-10) hold. It keeps the service and the promotion on one rule by construction.
- (A2, A4) `_write`'s `TIMED_OUT` versus `FAILED`: both outcomes are asserted (S4c `[write]`, S4d, S2b); a mutant swapping them is not listed separately.
- (A4, superseded by A5) `_left_at`'s unknown branch now has rows D-43 and D-46, killed by S2c (round 3 M2-4).
- (A5) Absorbing an O3 or O4 failure would need a new `try` statement, not a one-line mutant: the walk has one `except` clause (O1, O2) and none around a listing step or an `is_dir`. C3g fails every such cell.
- (A5) The status, department, created and updated conversions through `_stored_text` occur twice as stripped lines (the exit note's record and S1's), so they have no row; P5's per-field cases are their evidence, and P-17 kills the helper.
- (A5) `_present`'s `return None` is a line `stand_down.py` holds elsewhere; D-44 and D-46 cover the helper's unknown branch.
- (A4) Computing `remaining` before the existence check is a two-line move, not a single-line row: S4d `[the-check-outlasts-the-window]` fails on it (the check sleeps 0.4 s against a 0.2 s window).
- (A3 (2)) D-23 is killed by S4c `[write]` only because the stub counts a write when `write_entry` is called: Python 3.12's `asyncio.wait_for` with a timeout of zero or less cancels the coroutine before it starts, so a stub that counted inside its body would never see the mutant's second write once the clock reads past the deadline. S4c `[write]`, S3c and S4 run on the injected clock, so their order is fixed; S3 and S4b keep real time because their property is the real bound, with 1 s of headroom (a 1.5 s bound asserted under 2.5 s; D-34's doubled bound takes 3 s).

Mutants D-1, D-20 and D-32 take about 5 s to be killed, D-34 about 3 s and D-22 about 10 s (the stubs' sleeps and the doubled 1.5 s bound); every other row is killed in about two seconds or less (A3 (2): S3 and S4b take 1.5 s each on the honest code). A4: D-41's `[concurrency]` case takes 5 s (the test's bounded wait); on the honest code P4 takes about 3 s and L8 about 1 s.

## 11. Verified Against Codebase (2026-10-26, HEAD `fefd7f79`, tree `21d2a199c8b647d90488b029a0067ae6815c86bd`)

Read with the Grep and Read tools on this checkout (the S3 oracle). Every SEARCH block above was copied from these reads.

```
src/probos/knowledge/archive_store.py
  57-79: ArchiveEntry (source_kind str, author_did, source_episode_ids tuple, generation)
  87: PROMOTABLE_CLASSIFICATIONS = frozenset({"ship", "fleet"})
  93-102: class SourceKind(StrEnum) ... NOTEBOOK_FINDING = "notebook_finding"   (7.2)
  105-111: PromotionOutcome CREATED/PRESENT/ERASED/VETOED (S3)
  121-140: VetoOutcome, SourceState (S3)
  148-187: PromotionRecord: validates kind, non-blank timeline/ref/title/content, classification in PROMOTABLE,
           author fields str, source_episode_ids tuple of non-blank str, metadata JSON-serialisable
  302-316: _PROMOTE_SQL (one statement; erasure and veto checks)
  364-404: LABEL_THIS_CREW, LABEL_EARLIER_CREW, inheritance_label: f"[Inherited from the crew of generation {n}: not your own memory]"
  498-536: promote_entry: category = kind value; source_episode_ids = json.dumps(list(...))
  588: async def veto_source(self, source_kind, source_ref, reason, *, timeline_id="") -> VetoOutcome (S3; A1 line on 60e4415e)
  631, 654: source_state, entry_ids_citing (S3; A1 lines on 60e4415e)
  338: _CITING_SQL skips only '[]';  664-676: entry_ids_citing raises ValueError for a cell that is not a JSON list of strings (S3 A2)
  688-707: search: title/content LIKE
src/probos/knowledge/archive_promotion.py
  13-14: "- Ship's Records carry no source-episode ids ... (the lessons slice\n  adds them)."   (7.3 pair 1)
  25-33: imports; 33: from probos.knowledge.records_store import RecordsStore   (pair 2)
  40: ARCHIVE_READER = ""
  43-69: source_kind_for; 49-50 docstring bullet (pair 3); 55-57 the dict check and author (pair 4)
  86-87: @dataclass(frozen=True) / class PromotionPlan:   (pair 5)
  105-150: plan_promotion; 119-123 the read and the document-None branch   (pair 6)
  153-185: promote_ship_records (vetoed, S3);  204-213: review_promotion (S3)
src/probos/knowledge/lessons.py, src/probos/stand_down.py, src/probos/experience/commands/commands_stand_down.py: absent (S4-AV1)
src/probos/knowledge/erasure.py
  9: from collections.abc import AsyncIterator, Callable   (7.11 pair 1)
  88-113: ArchiveCitationsBlockErasure, _refuse_while_the_archive_cites (S3)
  128-141: class ErasureManager: __init__(episodic_memory, attachment_store, audit_log, *, archive_store=None) (S3)   (pairs 2, 3, 4)
  151-153: S3's check, then attachment_ids / unlinked   (pair 5)
  187, 202: S3's checks after the scans
  242-244: _forget_all docstring, total_count = 0   (pair 6)
src/probos/routers/security.py
  25: from probos.credential_store import crew_scope_token   (7.12 pair 1)
  26-28: ArchiveStore import (S3), erasure import (S3), require_crew_scope   (pair 2 on 28)
  78-79: @router.post("/forget") / async def request_erasure(   (pair 3)
  89: archive = getattr(runtime, "archive_store", None) (S3)
  90-91: manager = ErasureManager( / episodic_memory=...   (pair 4)
  93: audit_log=_get_audit_log(runtime),   (pair 5)
  109: except ArchiveCitationsBlockErasure as exc:  # AD-1341 S3 (D8): nothing was erased   (pair 6, S3 anchor)
src/probos/api.py
  45-46: comment / _BLOCKED_COMMANDS = {'/quit', '/debug'}   (7.9)
  74-109: _handle_slash_command: blocked first, else a fresh ProbOSShell per command
src/probos/experience/shell.py
  11-34: imports; 34: from probos.experience.commands import commands_schedule  # AD-812   (7.8 pair 1)
  63-125: COMMANDS; 122 the /schedule line   (pair 2)
  254-347: _dispatch_slash; 275 the /schedule handler   (pair 3)
src/probos/channels/base.py
  364-370: a non-paired sender's "/" text goes to api._handle_slash_command
  452-457: IntentMessage(intent="direct_message", params={"text", "from", "session": False}); runtime.intent_bus.send
src/probos/experience/commands/session.py
  110-120: direct_message from "captain", ttl_seconds=60.0 (AD-636);  138: runtime.intent_bus.send;  146-148: DmReply.from_intent_result(result)
src/probos/dm_reply.py
  898-912: DmReply.from_intent_result: body = result.result (str)
src/probos/types.py
  58-74: IntentMessage(intent, params, urgency, context, ttl_seconds=60.0, id, created_at, target_agent_id, thread_id)
  78-87: IntentResult(intent_id, agent_id, success, result=None, error=None, confidence=0.0, ...)
  667-692: Episode(id, timestamp, user_input, ..., agent_ids, ...)
src/probos/mesh/intent.py
  236-243: IntentBus(signal_manager, *, handler_latency_thresholds_ms=None);  457-464: subscribe(agent_id, handler, intent_names=None, *, latency_class)
  1133-1192: send(intent, *, raise_on_denial=False): needs target_agent_id; None when closed or denied; local handler first
src/probos/agents/system_qa.py
  318-334: asyncio.wait_for(agent.handle_intent(intent), timeout=config.timeout_per_test_seconds); total_timeout_exceeded
src/probos/runtime.py
  684: self.registry = AgentRegistry();  694: self.intent_bus = IntentBus(;  1080: self.episodic_memory;  1232: self.ontology
  1237, 2874: identity_service = IdentityService(...);  2209: records_store property;  3428: attach_current_timeline(ontology...instance_id)
src/probos/substrate/registry.py
  71: def all(self) -> list[BaseAgent]
src/probos/crew_utils.py
  69-76: is_crew_agent(agent, ontology=None): ontology.get_crew_agent_types() when given
src/probos/identity_service.py
  35-63: IdentityRef(slot_id, sovereign_id, did, callsign, agent_type);  79-95: resolve(key) -> IdentityRef | None
src/probos/ontology/service.py
  86-92: get_vessel_identity(): instance_id "unknown" when none is loaded;  162: get_crew_agent_types
src/probos/cognitive/episodic.py
  2352-2383: get_by_ids (degrades to [] on failure);  4109-4134: recent_for_agent(agent_id, k=5, *, ...): whole collection, then the shard
src/probos/cognitive/episodic_mock.py
  37: class MockEpisodicMemory;  121-126: store(episode, *, duplicate_policy);  215-218: recent_for_agent(agent_id, k=5): most recent first
src/probos/cognitive/eviction_audit.py
  23-27: DISPOSITION_ERASED;  139-180: record_eviction swallows a failure (WARNING)   (D14 B)
src/probos/knowledge/records_store.py
  32-43: _RESERVED_FRONTMATTER_KEYS (exit_note is not one);  46-51: classification levels;  70: NOTEBOOK_DEFAULT_CLASSIFICATION = "private"
  211-319: write_entry(author, path, content, message, *, classification, status, department, topic, tags, metrics, extra_frontmatter, ...)
  930-959: read_entry(path, reader_id, ...);  961-1001: list_entries(directory, ...): rglob("*.md"), skips _archived/
  1190-1200: _parse_document: yaml.safe_load; body .strip()
src/probos/config.py
  2658-2666: resolve_records_repo_path: {data_dir}/ship-records by default
src/probos/config_models/knowledge.py
  238-258: LLMRateConfig: per_agent_hourly_token_cap 0; max_concurrent_calls 6; interactive_reserved_slots 2
  358-362: ArchiveConfig(enabled=True, db_path="")
src/probos/__main__.py
  2642-2678: RESET_TIERS;  2905-3008: _cmd_reset (pidfile at 2987-3002; promotion first at 3004-3008)
  3180-3189: _read_instance_id;  3192-3198: _reset_records_store;  3277-3320: _promote_into_archive
  3323-3361: _show_promotion_plan;  3430-3489: pending (S3);  3492-3564: veto (S3; plan_promotion, record by source_ref)
src/probos/duty_schedule.py
  4, 69, 173-197: cron or interval duties, checked each proactive cycle
src/probos/agent_work.py
  1-24: AD-1347 S1: create and govern; runs nothing; claimed by eligible members
tests/test_ad1341_s1_archive_store.py
  51-74: _store, _rows, _record;  222-228: the closed SourceKind set   (7.4)
tests/test_ad1341_s1_reset_and_erase.py
  49-50: _SHIP, _NEXT_SHIP;  162-178: _config, _data_dir;  181-182: _records;  200-221: _archive_store, _rows, _reset;  235-241: _oracle_query
tests/test_ad1341_s3_review_cli.py
  36-47: _archive, _veto (S3)
tests/test_ad1341_s1_promotion.py   (A1, 60e4415e)
  413-420: test_the_service_imports_only_the_knowledge_layer: the exact probos.* imports of archive_promotion.py   (7.4a)
tests/test_ad1341_s3_erasure_cascade.py   (A1, 60e4415e)
  97-119: _traced (real FilesystemAttachmentStore and AuditLog; both episodes stored);  122-126: _traces   (X1b)
src/probos/knowledge/records_store.py   (A1)
  185-186: repo_path property (C3c);  949: read_entry calls frontmatter.get for a non-captain reader;  1196-1199: safe_load or {}
src/probos/knowledge/archive_promotion.py   (A1)
  55-56: source_kind_for returns None for frontmatter that is not a dict;  117: plan_promotion skips such a document unread
src/probos/knowledge/erasure.py   (A1)
  331-339: _delete_attachments unlinks each id with no other-owner check (BF-939, #1683)
tests/test_ad1340_s2a_lookup_route.py
  200-234: _runtime (MagicMock with a real SystemConfig), _client, _post
tests/test_ad1053_actionable_notifications.py
  36-51: IntentBus(SignalManager()) with a subscriber for direct_message
tests/test_ad700a_diagnostic_slash_command.py
  135-140: ProbOSShell.__new__ with MagicMock runtime/console/renderer, then _dispatch_slash
tests/test_layer_boundaries.py
  35-57: foundation modules (dm_reply, types); top-level files are "core"; knowledge may import knowledge
tests/test_ad1343_seam_registry.py, tests/fixtures/ad1343_seam_census.py:27-41
  the census counts CognitiveAgent work methods called on an agent; stand_down.py calls intent_bus.send, which is not one
```

## Absence Verified (2026-10-26)

**S4-AV1.** CLAIM: the new names are free.
RUN: Grep `EXIT_NOTE|exit_note|exit-notes|stand_down|StandDown|stand-down|parse_lesson|ExitNotesBlockErasure|LESSON_SECTIONS|commands_stand_down|knowledge\.lessons` over `src/`, `tests/`, `scripts/`, `config/`, `docs/development/`.
FOUND: `EXIT_NOTESTSCOLLECTED` only (`scripts/check_seam_contracts.py:42, 395`; `tests/test_ad1270b_seam_contracts.py:733`; `tests/test_ad1143_ablation_gating.py:37, 112-113`), pytest's exit code, unrelated.
HOLDS: yes.

**S4-AV2.** CLAIM: no CLI subcommand calls a running vessel's API, so an offline `probos stand-down` would need a new channel (D2 B).
RUN: Grep `httpx|127\.0\.0\.1|api_port|localhost:` and `/api/|api_url|probos_url` in `__main__.py`.
FOUND: Ollama warm-up and probes (`:204-314`, `:1030-1041`), `setup` probes (`:1172-1281`), and printed help strings (`:885-886`, `:915`, `:2233`). No request to the vessel's own API.
HOLDS: yes.

**S4-AV3.** CLAIM (corrected by A4; the original held on the S3 base, before 7.3 added the citation read): `source_kind_for` has two callers in `src`, `plan_promotion` and `exit_note_citations`.
RUN: `git show e1e97d25:src/probos/knowledge/archive_promotion.py`, grep `source_kind_for`; Grep `source_kind_for` in `src`.
FOUND: `archive_promotion.py:56` (definition), `:181` (`exit_note_citations`), `:229`, `:243` (`plan_promotion`), and the module docstring at `:5`; no other file.
HOLDS: yes.

**S4-AV4.** CLAIM: no test pins `_BLOCKED_COMMANDS`'s members or the whole `ProbOSShell.COMMANDS` set, so 7.8 and 7.9 break no test.
RUN: Grep `_BLOCKED_COMMANDS` in `tests`; Grep `ProbOSShell\.COMMANDS|_BLOCKED_COMMANDS|len\(shell\.COMMANDS|COMMANDS\) ==` and `in (shell\.|ProbOSShell\.)?COMMANDS\b|COMMANDS\.items\(\)|COMMANDS\.keys\(\)` in `tests`.
FOUND: no `_BLOCKED_COMMANDS` in tests. Only membership checks of single other commands (`test_shell.py:144-156`, `test_system_qa.py:1300-1302`, `:1401`, `:1480`, `test_ad700a_diagnostic_slash_command.py:148-149`, `test_bf914_channel_allow_lists.py:143` and others). No count or full-set pin.
HOLDS: yes.

**S4-AV5.** CLAIM: no test pins `SourceKind`'s members other than S1's closed-set test (7.4).
RUN: Grep `SourceKind\)|list\(SourceKind|set\(SourceKind|len\(SourceKind|SourceKind\.__members__|for .* in SourceKind` in `tests`.
FOUND: `test_ad1341_s1_archive_store.py:223, 226` (7.4 updates `:223`; `:226`'s "no episode" check still holds); `test_ad1341_s1_promotion.py:199` (a parametrised signature, not a set).
HOLDS: yes.

**S4-AV6.** CLAIM: `ErasureManager` is built in `src` only by the `/forget` route, so the new keyword reaches one builder.
RUN: Grep `manager = ErasureManager\(` and `audit_log=_get_audit_log\(runtime\)` in `routers/security.py`; S3-AV3 for the whole tree.
FOUND: `security.py:90`, `:93`, one each. S3-AV3: `ErasureManager(` only in `routers/security.py`.
HOLDS: yes.

**S4-AV7.** CLAIM: the mutation rows' lines are new and occur once in their files after §7.
RUN: Grep `if paths:|_attachment_ids_for_episode\(episode_id\)|Erase each episode in turn|self\._audit_log = audit_log` in `erasure.py`; `audit_log=_get_audit_log\(runtime\)|manager = ErasureManager\(` in `security.py`; the new files are new.
FOUND: no `if paths:` in `erasure.py`; each anchor once (`:139`, `:152`, `:243`; `:90`, `:93`). In `archive_promotion.py`, `timeline_id=timeline_id,` exists (`:135`), so P-7's line is `timeline_id=note_timeline,  # ...`, a different stripped line. The two `if path.startswith(f"{EXIT_NOTES_DIR}/"):` lines differ by P-2's comment.
HOLDS: yes.

**S4-AV8.** CLAIM: the stand-down adds no AD-1343 seam: it calls no `CognitiveAgent` work method on an agent.
RUN: Read `tests/fixtures/ad1343_seam_census.py:27-41`; read 7.6.
FOUND: the census counts `CognitiveAgent`'s classified coroutines and synchronous work starters called on an agent receiver. 7.6 calls `bus.send(intent)` (an `IntentBus` method), as `session.py:138` and `channels/base.py:457` do, and no `handle_intent`, `decide`, `act`, `report` or `complete`.
HOLDS: yes, as far as reading shows; M2's gate runs the census (§Not verified, item 2).

## Verified for A2 (2026-10-26, candidate `54cb4027`; `git diff 20c1ec00 54cb4027 --stat` lists neither `records_store.py` nor `cognitive_agent.py`, so their base text is the candidate's)

- `records_store.py:961-1001` `list_entries`; `:977` `rglob`; `:982-987` the `try` that skips any read or parse failure; `:1190-1200` `_parse_document` folds `yaml.YAMLError` into `{}`; `:184-186` `repo_path`; `:930-959` `read_entry` skips classification for `"captain"`; `:321` `write_text` publishes before `:324-326` git; `:1239-1252` `_git_sync` returns on a non-zero exit and raises only from `subprocess.run` (`timeout=30`); `:1254-1262` `_commit` swallows.
- `oracle_query_tool.py:70-72` (`_MAX_ENTRY_CHARS = 1200`, `_MAX_OUTPUT_CHARS = 6000`), `:119-129` `_cap_entry`, `:143-161` `_render`; `oracle_service.py:1180` the archive entry's content (`{label}\n[{category}] {title}\n{content}`), `:1175` score at most 1.0, `:763` the 300-character preview; `archive_store.py:366-406` the labels; `provenance.py:56-58`, `:80` the marker and `render`. The budget: marker 39 + 1 + label 67 + 1 + `[exit_note] Exit notes of ` 26 + callsign 32 + 1 + origin line (92 + 32 + 48 + 64) + 2 + render (67 + 700) = 1,172. The arithmetic checks against the reviewer's measured short note (`raw-oracle= 322`, `evidence-s4orch-m1-f4-confirm.txt:4`).
- `ontology/loader.py:99`, `:162` the instance id is `str(uuid.uuid4())` (36 characters, inside 64).
- `cognitive_agent.py:4692-4715` the gate (`:4711-4715` the group and vision checks), `:4754` the dispatch, `:4382` the decision step's call, `:3214`, `:4206`, `:4254` the other readers, `:5190-5205` the promotion arming, `:5404` `run_with_promotion`, `:2955` `perceive` keeps `params`, `:1352` `_promoted_turn_tasks`, `:10374` `_format_direct_message_trigger`; `config/system.yaml:469-470` (`dm_agentic: enabled: true`), `:624` (`promote_to_task_after_seconds: 40`); `mesh/intent.py:473` `subscribe` replaces an agent's handler (S16 re-subscribes).
- `erasure.py:181-182` (S3 then S4 in `forget_episode`), `:218`, `:233` (S3 in the scans), `:275` (S4 at the top of `_forget_all`).
- `scripts/check_architecture_principles.py:652-677`: only a bare-statement scheduling call is an unowned-task finding, and `:661-668` counts every `.create_task` attribute call. A4: 7.6's `asyncio.create_task` calls sit inside a list (assigned, not bare), so they are no finding; `:661-668` counts them into `broad_create_task_calls`, which `:1071` reports and no gate or test reads. A2's `asyncio.ensure_future` broke Engineering Principles' Async Discipline (`docs/development/engineering-principles.md:84`, "Never use `asyncio.ensure_future()`").
- The reviewer's probe `logs/ad1341s4r1/probes-m2/test_additional_seams.py:133-181` builds the S16 rig (real `CognitiveAgent`, `WorkItemStore`, `ChatThreadStore`, `TrustNetwork`, `AgentRegistry`, a `BaseLLMClient` subclass) on the candidate and fails on its assertion, not its construction.

## Absence Verified (A2, 2026-10-26)

CLAIM: the A2 names are free, and no `strict` parameter exists on the records listing.
RUN: Grep `bounded_turn|LESSON_MAX_CHARS|EXIT_NOTE_\w+_MAX_CHARS|exit_note_lesson|exit_note_provenance_ok|is_exit_note_text|BOUNDED_TURN_PARAM|strict: bool` over `src/`; Grep `strict` over `records_store.py`; Grep `bounded_turn|exit_note_lesson|exit_note_provenance_ok|is_exit_note_text|LESSON_MAX_CHARS|_deny_reading|_unreadable\(` over `tests/`.
FOUND: `strict: bool` only at `episodic.py:2781`, `llm_client.py:969`, `agentic_loop.py:1197`, `:2918` (other classes); `strict` in `records_store.py` only in comments (`:106`); in `tests/` only the file name `test_ad1208_cost_bounded_turns` and other files' local `_unreadable` helpers.
HOLDS: yes.

CLAIM: every `RecordsStore.list_entries` caller in `src` keeps the default (§5).
RUN: Grep `\.list_entries\(` over `src/`.
FOUND: the 16 records-store calls listed in §5 (`commands_gap.py:51` … `routers/records.py:212`, and `stand_down.py:197`, `archive_promotion.py:167`), plus skill-catalog `list_entries` (another class: `commands_skill.py:120`, `jit_bridge.py:203`, `use_skill_tool.py:114`, `:174`, `runtime.py:6494`, `routers/skills.py:194`, `routers/tools.py:118`, `skill_bridge.py:55`, `:108`, `skill_catalog.py:383`, `:420`).
HOLDS: yes; only `exit_note_citations` and `run_stand_down` pass `strict=True`.

CLAIM: no test reads `_conversational_agentic_will_run`'s source text.
RUN: Grep `getsource.*will_run` over `tests/`.
FOUND: none. 15 test files call the method (`test_ad1065`, `ad1070`, `ad1070a`, `ad1156_plan_mode_learning`, `ad1165`, `ad1167`, `ad1177`, `ad1180`, `ad1208`, `ad1224`, `ad1246`, `ad1257`, `ad1322`, `ad1324`, `bf698`); six are in M2's gate, and the broad gate runs the rest.
HOLDS: yes.

CLAIM: no `asyncio.TaskGroup` in `src`.
RUN: Grep `TaskGroup\(` over `src/probos`.
FOUND: none.
HOLDS: yes (A2 adds none).

## Verified for A4 (2026-10-26, repaired head `e1e97d25`, tree `908866a49810c1d5603200c612c1c6545728b4cd`; `git diff --stat ddf0e295 e1e97d25 -- prompts/` is empty, so this contract is A3's)

Read with `git show e1e97d25:<path>` and grep.

- `records_store.py:3-5` the stdlib imports (no `os`, no `fnmatch`); `:156-164` `_jaccard_similarity`, `:167` `class RecordsStore`; `:961-1013` `list_entries`: `:981` `search_path`, `:984` `for md_file in sorted(search_path.rglob("*.md")):`, `:992-994` the strict file re-raise; `:316-317` `yaml.dump`, then `f"---\n{fm_yaml}---\n\n{content}"`; `:321` `write_text` before `:324-326` git (only with `auto_commit`); `:1202-1212` `_parse_document`, `:1205` `raw.split("---", 2)` (R2-F3, register R25).
- `lessons.py:59` `_NAMES` (ASCII keys), `:60` `_SECTION`, `:106`, `:109` `_NAMES[match.group(1).lower()]` (R2-F2's `KeyError`); `:76` `_UNSTORABLE` (NUL and surrogates only) and `:126` its one use; `:79` `_NOT_ONE_LINE`; `:211-220` `is_exit_note_text`.
- `archive_promotion.py:131` the id check (P-15), `:179` the strict citation read, `:227` `plan_promotion`'s default listing (R20).
- `stand_down.py:140-157` `_offer` (`:152` the id check R2-F4 names); `:235` the bound check; `:247-254` the strict first read, whose exception becomes `StandDownRefused` before any turn is created (unchanged); `:261-294` `_write`: `:264` `remaining` before `:267`'s awaited `read_entry` (round 2 M2-2), `:289` the unconditional `unlink` (M2-1); `:300` the recall's degrade (D-39); `:320` D-2's line; `:374` `ensure_future`. `commands_stand_down.py:25-27` the usage guard (C-2), `:37-39` prints any turn's path.
- `tests/test_ad1341_s1_reset_and_erase.py:49` `_SHIP = "ship-did-alpha-0001"`; `:162-166` `_config`; `:181-182` `_records` with `auto_commit=False` (so `write_entry` awaits nothing, and S4d's late return never yields); `:212-218` `_reset`.
- Python 3.12 `re` (docs.python.org/3.12/library/re.html, fetched 2026-10-26): with IGNORECASE, `[a-z]` also matches U+0130, U+0131, U+017F and U+212A; `(?a:...)` switches a group of a Unicode pattern to ASCII-only matching, for that group only. `os.walk`'s `onerror` may raise to abort the walk.
- D-2 by reading: S4 sets the clock to 1,000 inside the data analyst's ask. With D-2's check removed, `_write` computes `remaining = deadline - clock()` below zero and returns `TIMED_OUT`, so S4's outcomes are unchanged (equivalent). S3b (a real-clock reply returning after its 0.2 s turn inside a 60 s window) and S3c `[slow-recall]` (the clock at 0.65 against a 0.5 s turn) reach the write under the mutant and fail. S3c `[recall-runs-out]` times out before the ask and never reaches D-2.

## Absence Verified (A4, 2026-10-26)

**A4-AV1.** CLAIM: no `src` file other than the stand-down names an exit-note path, so the stand-down is the only in-process writer of `exit-notes/`.
RUN: Grep `exit-notes|EXIT_NOTES_DIR|exit_note_path\(` in `src`; `git show e1e97d25:src/probos/stand_down.py` and `archive_promotion.py`, the same grep.
FOUND: `lessons.py` (definitions); `archive_promotion.py:39`, `:71`, `:136`, `:179`, `:235` (readers); `stand_down.py:269` (`write_entry`) at the path from `:350`, and the tag `"exit-notes"`.
HOLDS: yes. The writers left are R14's (a hand edit, a file-writing tool). Round 2's M2-1 probe built two `RecordsStore` instances on one repository, which ProbOS never does.

**A4-AV2.** CLAIM: nothing but S2b depends on the stand-down removing a failed write's note.
RUN: grep `unlink` in this contract.
FOUND: `stand_down.py`'s rollback (7.6) and S2b's `[cannot-remove]` patch (7.10); the rest are attachments (BF-939, M3), unrelated.
HOLDS: yes.

**A4-AV3.** CLAIM: `ensure_future` appears once in the slice, and nothing pins it.
RUN: `git show e1e97d25:src/probos/stand_down.py`, grep `ensure_future|create_task`; grep this contract.
FOUND: `stand_down.py:374` only; the contract's 7.6 line and the A2 verified bullet.
HOLDS: yes.

**A4-AV4.** CLAIM: `docs/research/reference-projects.md` has no row on file listing, frontmatter or terminal-safe text.
RUN: `git show e1e97d25:docs/research/reference-projects.md`, grep -i -c `frontmatter|front matter|yaml|terminal|ansi|scandir`.
FOUND: 0.
HOLDS: yes.

**Not verified for A4 (the orchestrator verifies by running):** `(?a:...)` under `re.IGNORECASE` (L8 runs it); the native directory denial (C3e `[native-*]`: a share-nothing handle with `FILE_FLAG_BACKUP_SEMANTICS` on Windows, as the reviewers' WinError 32 probe used); P4's PyYAML quoting of every admitted value; S4d's margins on this host.

## Verified for A5 (2026-10-26, committed head `bbc64351`, tree `963adf2b1c3021675cdd4e931ef0d8c66e58b377`; `git diff --stat 6aafab3c bbc64351 -- prompts/` is empty, so this contract is A4's)

Read in the checkout of `bbc64351` with Grep and Read.

- `records_store.py:169-186` `_markdown_files_or_raise` (`:180-182` the `onerror` callback, `:184` `os.walk`, `:185` dirs and files matched by `fnmatch`); `:983-1039` `list_entries` (`:1005` `search_path` through `_safe_path`, `:1008` the strict or default walk, `:1016` `read_text`, `:1018-1022` the `OSError` branch with `md_file.is_file()`); `:952-981` `read_entry` (`:962` `_safe_path`, `:963` `exists()` returning None, `:966` `read_text`); `:1240-1251` `_safe_path` (`:1245` `resolve()`); `:299-300` `write_entry`'s `exists()`, `:343` `write_text`; `:34-45` `_RESERVED_FRONTMATTER_KEYS` (no `claim_id`).
- `archive_promotion.py:48` `logger`, `:53` `ARCHIVE_READER = ""`, `:88-99` `_title_for` (`:96` `str(topic) if topic else ""`), `:114-115` the never-raises claim, `:157-161` the exit note's three `str()` conversions, `:179-183` the strict listing and the second read through `read_entry`, `:227` `plan_promotion`'s default listing, `:252-266` S1's record (`:260` the author, `:262-265` four metadata values). `git show 20c1ec00:src/probos/knowledge/archive_promotion.py` holds the same five at `:141-146` (pre-existing in S1).
- `archive_store.py:87` `PROMOTABLE_CLASSIFICATIONS = frozenset({"ship", "fleet"})`; `:172-188` `PromotionRecord` requires `str` author fields and JSON-serialisable metadata.
- `stand_down.py:251-261` the deadline and the strict first read; `:267-272` `_left_at` (`Path.exists`, `except OSError`); `:284` the guard's `Path.exists`; `:389` the turn tasks. `commands_stand_down.py:37-44` the turn lines and the footer counting `WRITTEN` only.
- `routers/security.py:81-93` `_pending_exit_note_citations` lets a failed read propagate; `:108` it runs before `:109` builds the manager.
- `pyproject.toml:9` `requires-python = ">=3.12"`.
- Round 3's executed evidence: the orchestrator's single-fault probe (one `is_dir` fault; `[]` returned) and its matrix on `bbc64351` (6 of 36 operations, each an `is_dir`, returned a shorter list for `PermissionError` and `OSError(EIO)`); the M1 reviewer's `0x` and 4,000 digits through the real store and the real reset (exit 1).

## Absence Verified (A5, 2026-10-26)

**A5-AV1.** CLAIM: `exit_note_citations` and `run_stand_down` are the only strict callers, and only `list_entries` calls `_markdown_files_or_raise`.
RUN: Grep `_markdown_files_or_raise|list_entries\([^)]*strict` over `*.py`.
FOUND: `records_store.py:169`, `:1003`, `:1008`; `archive_promotion.py:179`; `stand_down.py:253`; `tests/test_ad1341_s4_lessons.py:686`, `:712`.
HOLDS: yes.

**A5-AV2.** CLAIM: the stand-down makes two filesystem existence checks and no other filesystem call.
RUN: Grep `exists\(|is_file\(|is_dir\(|\.stat\(|os\.` in `src/probos/stand_down.py`.
FOUND: `:270` (`_left_at`), `:284` (the guard); the rest are prose and imports.
HOLDS: yes; O7 covers both.

**A5-AV3.** CLAIM: the promotion service makes no filesystem call of its own.
RUN: Grep `exists\(|is_file\(|is_dir\(|\.stat\(|scandir|rglob|glob\(` in `archive_promotion.py`.
FOUND: none.
HOLDS: yes; its reads are `list_entries` (O1 to O5) and `read_entry` (O6).

**A5-AV4.** CLAIM: the promotion converts stored frontmatter values with `str()` at nine places and no others.
RUN: Grep `str\(frontmatter\.get` and `str\(topic\)` in `archive_promotion.py`.
FOUND: `:158`, `:159`, `:160`, `:260`, `:262`, `:263`, `:264`, `:265`; `:96`.
HOLDS: yes; all nine go through `_stored_text`.

**A5-AV5.** CLAIM: no committed S1 to S4 test patches `Path.exists`, `Path.lstat` or `Path.stat` except S4d.
RUN: Grep `"exists"|"lstat"|"stat"|Path\.exists|Path\.lstat|Path\.stat|"is_file"` over `tests/test_ad1341_s*.py`.
FOUND: `tests/test_ad1341_s4_stand_down.py:454`, `:472` (S4d).
HOLDS: yes; S4d moves to `Path.lstat` with the guard (C236, C237).

**A5-AV6.** CLAIM: no test pins `os.walk`, `_title_for` or the `str()` conversions as text.
RUN: Grep `str\(frontmatter|os\.walk|_title_for|_stored_text` over `tests/`.
FOUND: `test_ad1341_s4_lessons.py:698` (C3f's docstring, rewritten by C221); `test_bf896_dispatcher_confinement_seam.py:117` (its own walk); two unrelated names.
HOLDS: yes.

**Not verified for A5 (the orchestrator verifies by running):** Python 3.12.13's `pathlib` internals the tests rely on. The orchestrator read `_ignore_error` at `pathlib.py:45-54`, `is_file` at `:886-896`, `Path.walk` at `:1112-1156` and the wildcard selector at `:191-215`. Also unverified here:
- `Path.resolve()` calls `stat()` in non-strict mode and re-raises only a link loop (so `_deny_stat` compares by name, never through `resolve()`).
- `Path.lstat()` goes through `Path.stat(follow_symlinks=False)`; S8d patches both, so it does not depend on it.
- `DirEntry.is_dir` returns False itself for an entry that no longer exists.
- `is_dir(follow_symlinks=False)` is true for a junction on Windows.
- C3g's operation count on this host, and X8's 500 under `_deny_entry_type`.

## Not verified (the orchestrator verifies by running)

1. **The live archive** (`%LOCALAPPDATA%\ProbOS\archive\archive.db`, read-only; the vessel stays up): `PRAGMA user_version` (1) and `SELECT count(*) FROM archive` (0). The bridge allows no `sqlite3`; I did not open it. No S4 fact depends on it.
2. **The AD-1343 census and the architecture-fitness baseline** on M2 and M3: `tests/test_ad1343_seam_registry.py`, `tests/test_ad1270b_architecture_fitness.py`. Both are in the focused gates.
3. **The phantom precheck:** run by the orchestrator on A0 (29 candidates, `logs/ad1341s4a1/phantom-s4-draft.txt`); triaged in §12 (A1). Re-run it on A1: the 13 `Lesson` candidates should be gone, and the 12 `CrewMember`, the URL, the two stdlib classes and `IntentMessage.py` remain, as recorded.
4. **`list_entries` on a missing directory** returns `[]` (Python 3.12 `Path.rglob` on a path that does not exist): C3b and S1's first stand-down exercise it.
5. **The live crew size**, and so a stand-down's cost and wall time: the number of crew agents `/manifest` shows. Not read. At concurrency 2 and a typical 1:1 turn of 20-60 s, 15 to 20 agents take about 3 to 10 minutes. The 900 s window caps it.
6. **The wall time of `recent_for_agent` on the live collection.** It reads the whole ChromaDB collection per call and blocks the loop, once per agent (register R8).
7. **A cancelled DM turn on a live agent** (a turn past 180 s) leaves the agent serving its next message normally. System QA cancels turns the same way. Not exercised against a live agent.
8. **`IntentBus.send`'s direct path** with a fresh `IntentBus(SignalManager())` and no authorization hook delivers to the subscriber: AD-1053's test relies on it (`test_ad1053_actionable_notifications.py:36-51`). S12 confirms it.

## S3 anchors this contract depends on

The orchestrator re-verifies these on the real post-S3 merge. If one changed, the contract returns to the Architect.

**A1 (2026-10-26): re-verified on the S3 candidate `60e4415e` (tree `bd69c9b2fb0621db01e733dcbe39f2dea218b422`), after S3's round-1 repair.** Every A0 SEARCH applied once there (the orchestrator's dry run). Both textual anchors hold (`erasure.py:135-136`, `routers/security.py:109`). S3's repair changed `archive_store.py` and S3's tests, none of S4's anchors. Line shifts only: `veto_source` `:588`, `source_state` `:631`, `entry_ids_citing` `:654` (§11). New S3 facts S4 relies on or must not: `entry_ids_citing` raises `ValueError` for an unreadable cell (S4 does not call it; D16); S3's register R11 (BF-939, #1683) and R13 (D16; register R16, R17).

**Textual (the SEARCH contains S3's text):**

| Pair | File | S3's text | S3 source |
|---|---|---|---|
| 7.11 pair 3 | `src/probos/knowledge/erasure.py` | the `archive_store` keyword line of `ErasureManager.__init__` and the `) -> None:` line after it (see 7.11 pair 3's SEARCH) | S3 7.8 pair 3 |
| 7.12 pair 6 | `src/probos/routers/security.py` | `    except ArchiveCitationsBlockErasure as exc:  # AD-1341 S3 (D8): nothing was erased` | S3 7.9 pair 4 |

**Semantic (S4 calls S3's names or relies on its behaviour):**

| S3 name or behaviour | Where S4 uses it |
|---|---|
| `ArchiveStore.source_state` and `SourceState.outcome` | `exit_note_citations` |
| `veto_source`, `VetoOutcome.RECORDED` | C1, C2, X3 |
| `PromotionOutcome.VETOED`, `PromotionReport.vetoed` | C2, X2 |
| `review_promotion`, `PendingSource` | C4 |
| `probos archive veto` and `_veto_pending_source` (finds a source in `plan_promotion` by `source_ref`, exit 0 on record) | X2 |
| the route's local `archive = getattr(runtime, "archive_store", None)` | 7.12 pair 4 |
| `ErasureManager(..., archive_store=)` | M3 tests |
| `ArchiveCitationsBlockErasure` | S15 |
| `runtime.archive_store` (the read-only property) | X2 |
| `tests/test_ad1341_s3_review_cli.py::_veto` | X2 |
| `entry_ids_citing` reading S4's canonical cell (`json.dumps(list[str])`) | S15 |
| `tests/test_ad1341_s3_erasure_cascade.py::_traced`, `_traces` (S3 A2's real attachment store and audit log) | X1b |

**Base text S3's REPLACE keeps** (S4 anchors on it):

- `erasure.py`: the two attachment lines (S3 pair 4) and `self._audit_log = audit_log` (S3 pair 3).
- `security.py`: `manager = ErasureManager(` with its next line (S3 pair 2), `audit_log=_get_audit_log(runtime),` (S3 pair 3), and the two import lines (S3 pair 1).
- `archive_promotion.py`: lines 13-14 (S3 pair 1 appends after them), and the `PromotionPlan` lines (S3 pair 3 keeps them).
- The tracker anchors.

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 1 (`runtime.X`) | The tests set `runtime.records_store`, `runtime.archive_store` and `runtime.config` on S2a's `MagicMock` runtime. `records_store` is a property (`runtime.py:2209`); `archive_store` is S3's property; `config` is an attribute. `runtime.config.archive.enabled` is a real `SystemConfig` field (`ArchiveConfig.enabled`) |
| Pattern 2 (`Name.attr`) | Enum members are upper case and new (`TurnOutcome.WRITTEN`, `SourceKind.EXIT_NOTE`) or S3's (`VetoOutcome.RECORDED`, `PromotionOutcome.VETOED`). `ProbOSShell.COMMANDS` exists. §13's URLs may be reported as candidates (S3 precedent) |
| Pattern 3 (`Name(`) | New classes (`LessonLearned`, `CrewMember`, `TurnResult`, `StandDownReport`, `StandDownRefused`, `ExitNotesBlockErasure`). Existing classes (`IntentBus`, `SignalManager`, `IntentMessage`, `IntentResult`, `IdentityRef`, `MockEpisodicMemory`, `Episode`, `RecordsConfig`, `RecordsStore` as a base class, `ErasureManager`, `JSONResponse`, `Console`, `StringIO`, `SimpleNamespace`, `MagicMock`, `PromotionRecord`). Stdlib exceptions. `_Unlistable` starts with an underscore |
| Kwarg check | `records.write_entry(author=, path=, content=, message=, classification=, status=, topic=, tags=, extra_frontmatter=)`, all at `records_store.py:211-225`. `memory.recent_for_agent(..., k=)` (`episodic.py:4110`). `bus.subscribe(..., intent_names=)` (`intent.py:461`). `IdentityRef(...)` and `IntentMessage(...)`, `IntentResult(...)` keywords (§11). `archive.veto_source(..., timeline_id=)` (S3, `archive_store.py:588`). New: `run_stand_down(..., turn_seconds=, window_seconds=, concurrency=, clock=)`, `ErasureManager(..., exit_note_citations=)` (passed as a mapping in the tests, as S3 did) |
| Layer | `knowledge/lessons.py` imports only stdlib. `knowledge/archive_promotion.py` imports `knowledge.lessons` (same layer). `stand_down.py` is a top-level (core) module. It imports `knowledge.lessons`, `dm_reply` and `types` (foundation), and `crew_utils` lazily. `experience/commands/commands_stand_down.py` imports core lazily. `routers/security.py` imports `knowledge` (as it already does) |
| Store registry | no new table or `.db`; `exit-notes/` is a Ship's Records directory |
| Config facade | no new config field or `probos.config` name |
| AD-1343 census | no `CognitiveAgent` work method is called on an agent (S4-AV8). No name in `STOP_CALLEES`, `GUARD_CALLEES` or `RECORDED`. No `.complete(`, `.finalize(`, `.report(` or `.invoke(` call |
| Unowned tasks | none. `asyncio.gather` over coroutines; `asyncio.wait_for` owns its inner task |
| SRP | `ErasureManager` stays at 15 methods (the check is a module function). `archive_promotion.py` gains two module functions |
| BF-919 isolation | every archive, records repository and memory in the new tests lies under `tmp_path` |
| Hidden pins | `test_ad1341_s1_archive_store.py:223` (7.4) and, found by running (A1), `test_ad1341_s1_promotion.py:413-420`, the exact import set of `archive_promotion.py` (7.4a). A1 enumerated the rest: Grep `== \{|== frozenset|_importers|__all__|dir\(|ast\.Import|import_module` over `tests/test_ad1341_s*.py`, and `ast\.ImportFrom|_BLOCKED_COMMANDS ==|COMMANDS\) ==|len\(SourceKind` over `tests/`. These hold: `archive_store.py:251` (ArchiveStore's public surface; S4 adds no method), S1's `promote_entry` census (`:434`), `erase_entry`/`record_generation` (`reset_and_erase.py:601`), S3's `veto_source` only `__main__.py`, `source_state` only `archive_promotion.py`, `entry_ids_citing` only `erasure.py`, `ErasureManager(` only `routers/security.py`. `test_ad1328_s2a_gate.py:1457` pins cmd.exe built-ins, unrelated |
| Phantom precheck, run (A1: the orchestrator's run on A0, 29 candidates) | **No true phantom.** (1) `ET_lessons.pdf`: a URL in §13. (2) `SimpleNamespace`, (3) `StringIO`: stdlib (`types`, `io`), imported in 7.10. (4-15) `CrewMember(...)` with `agent_id`, `sovereign_id`, `did`, `callsign`, at 7.6 `crew_for_stand_down`, 7.10 `_member` and 7.13 `_AGENT`: each builds `probos.stand_down.CrewMember` (7.6: `agent_id`, `agent_type`, `sovereign_id`, `did`, `callsign`), never a stand-in. The checker resolved the name to `agent_work.CrewMember` (`agent_work.py:155`). Kept, and the collision recorded: the name is local to S4's three files (about 36 sites), and nothing imports both (`agent_work.CrewMember` is imported only by `cognitive/crew_directory.py:14` and `tests/test_ad1347_s1_agent_work.py:37`). (16) `IntentMessage.py`: prose, the path `intent.py` (§11, §12) read as an attribute. (17-29) four field reads and nine `render(...)` calls: the checker resolved S4's class to `evolution_store.py:73`'s `Lesson`, which `probos.cognitive.self_improvement` re-exports (`__init__.py:16`). **Renamed to `LessonLearned` (A1):** S5's after-action reports build on this format, so the collision would recur in every later precheck and import. `LessonLearned` is free: Grep `LessonLearned|ExitNoteLesson` over `src`, `tests`, `prompts`, `docs`: no match (2026-10-26) |
| A2 shared contracts | `records_store.py` gains one keyword-only parameter and one `except OSError` branch (the default is behaviour-identical); `cognitive_agent.py` gains one condition and four docstring lines, with no method and no callee; `oracle_query_tool.py` is unchanged. Hidden pins to grep before building: `rg -n "_conversational_agentic_will_run\|vision_messages" tests/` and `rg -n "list_entries" tests/test_records_store.py` |
| Size | `lessons.py` about 175 lines; `archive_promotion.py` +90; `stand_down.py` about 330; `commands_stand_down.py` about 50; `erasure.py` +35; `security.py` +40; the tests about 330, 460 and 290. A2: `lessons.py` about 235; `stand_down.py` about 420; `records_store.py` +14; `cognitive_agent.py` +6; the tests about 470, 900 and 400 |

## 13. Prior Art and Blind Spots

**Date used for overdue rows:** 2026-10-26.

**Internal work used:**
- #1569 comment 1 (the Captain's lessons-learned amendment): the four sections (D6). Its chain-of-command review moves to S5 (D12). Its "just culture" note is for whoever next touches trust scoring; nothing here scores a note.
- `docs/research/harness2-absorption.md:43`: "A lesson record that carries its evidence ... Matches the lessons-learned shape used for crew lessons". Adopted: a note carries the ids of the episodes it rests on (D9). The evidence verdicts it pairs with are AD-1338's.
- `docs/research/agent-situation-awareness-architecture.md:250` ("Turnover notes: specific items from the outgoing watch stander"): the watch-turnover model the stand-down follows. The outgoing agent writes for the oncoming one in its billet, so the path is keyed by billet (agent type).
- Chapel's request for a structured exit-notes window (the Captain's memory note "Pre-Reset Exit Notes") and the generational knowledge transfer case study: the prompt addresses the successor directly (D4).
- S2's minority-report label and RS2-6, and S1 A3 (a label never withholds or stops a run): D15's origin line and D10's never-raise rule.
- `agents/system_qa.py:318-334`: bounded agent turns with a per-turn and a total timeout, cancelled by `asyncio.wait_for` (D5).

**External prior art:**
- Kubernetes pod termination: a `preStop` hook runs before termination, bounded by `terminationGracePeriodSeconds`, with the forced kill as the backstop. A hook that runs over the grace period does not hold the pod. Adopted as the stand-down's shape: an optional pre-stop step whose own bounds keep it inside the window, and a reset that does not wait for it. Different from Kubernetes, the stand-down is a separate step the Captain runs, not a hook on the reset. <https://linkerd.io/2.13/tasks/graceful-shutdown/>, <https://oneuptime.com/blog/post/2026-02-09-termination-grace-period-clean-shutdowns/view>
- Naval watch turnover and the passdown log (command watch instructions): the departing watch turns over before relief; the passdown log holds items of general interest; items in effect for more than 30 days move into a formal notice. Adopted: the note is the turnover (D4), and promotion is the move from log to formal record. <https://cnreurafcent.cnic.navy.mil/Portals/78/NSA_Naples/Documents/NSA%20Naples%20Instructions/NAVSUPPACTNAPLESINST%201601_4J%20COMMAND%20WATCH%20ORGANIZATION%20AND%20STANDING%20ORDERS.pdf>, <https://www.netc.navy.mil/Portals/46/NETC/staff%20inst/16011K.pdf>
- Lessons-learned formats: the searches found the observation, discussion and recommendation structure as a general convention, for example a HUD lessons-learned guide with an "observation-discussion-recommendation format". JLLIS's own template sits behind a CAC login, so I could not read it. The four sections come from the Captain's comment 1; nothing found contradicts them. <https://www.hud.gov/sites/dfiles/OCIO/documents/ET_lessons.pdf>, <https://www.airuniversity.af.edu/LeMay/Display/Article/4277126/lessons-learned/>
- Agent self-handoff notes (session-handoff skills; a product changelog in which "the agent now writes its own handoff note ... what it was doing, what it decided, what comes next"). Adopted: the agent writes its own note in fixed fields, instead of a summary written about it. Not adopted: their trigger is a full context window, not an order; evidence is vendor-grade, with no evaluation found. <https://playcode.io/changelog/agent-hands-off-context-to-itself>, <https://skills.cat/skills/softaworks/agent-toolkit/session-handoff>
- `docs/research/reference-projects.md`: no row is a lessons-learned, shutdown-hook or handoff system, so I examined and updated no row. None of the four projects searched above is a row, and none is proposed: they are references for this slice, not projects to track.

**Blind spots found:**
1. **The reset cannot run agents.** Hence a live step before it (D2), and a reset that never depends on it.
2. **The window between note and archive.** An erasure in that gap would leave a citation the reset archives. Fixed by D14; the snapshot bound is registered (R2).
3. **A citation the agent invents.** Fixed by handles mapped to the episodes it was shown (D9).
4. **A bad note blocking a reset.** Fixed by a rule that withholds and never raises (D10, P2).
5. **Attribution to the wrong generation** when a promotion is skipped. Fixed by the note's own timeline (D9).
6. **Concurrent git writes** to Ship's Records. Fixed by one write lock (7.6).
7. **The HXI and the channels reaching an expensive order.** Fixed by `_BLOCKED_COMMANDS` (D2).
8. **A later crew reading a note through the records tier, unlabelled.** Mitigated by the origin line (D15); registered (R5).
9. **Callsign reuse across generations** colliding paths. Avoided by agent type (D7); same-type crew registered (R9).
10. **A note growing past the tool cap** and losing its label to AD-1148's elision. Bounded by D6 (L6).
11. **Citations dangling after the reset** that wipes their episodes. Registered (R4); S5's continuous promotion is where they stay live.
12. **A document the promotion skips unread** (frontmatter that is not a mapping) made the citation read raise in `read_entry`, so every AD-754 erasure would fail while it sat in `exit-notes/`. A1 found it by asking S3's round-1 question (M1-F1, cells a read cannot interpret) of this read. Fixed: the read skips what `plan_promotion` skips (C3c, P-12).
13. **A side effect before the refusal** (S3's M3-F1) asked of S4's check: X1b runs it with S3's real attachment store and audit log (E-5, E-6).
14. **A shared attachment blob** (BF-939, #1683; S3's R11): an erasure of an uncited episode can unlink a cited episode's blob while its note waits. S4's ids are unaffected; registered (R16), before S5.
15. **A hidden pin**, S1's import census of `archive_promotion.py`, found only by running (A1, 7.4a). Enumerated since (§12).
16. **(A2) A consumer between the service and the agent** (M2-1): the DM consumer promoted a long turn into background work, so "bounded by the service" did not bound the agent. Fixed at the one gate (7.9a), and tested through the real consumer (S16).
17. **(A2) A failure the shared listing hides** (M1-F1, M3-F1): a skip inside `list_entries` looked like an absent note. Fixed with a strict read (7.3a); the reset keeps S1's tolerance (R20).
18. **(A2) The last consumer's own cap** (M1-F4): the arithmetic was done against AD-1148's 6,000, not the tool's 1,200. L6 now runs through the real tool.
19. **(A2) A format that is not closed under its own writer** (M1-F3), and **an archive that receives a different string from the one validated** (M1-F5). Fixed by refusal (L1b) and by requiring the canonical body.
20. **(A2, A4) A write that publishes before it fails** (M2-4). A2 removed the published note; A4 reports it instead, because the removal could delete a document another writer put there and could not run on cancellation without a store change. The Captain's review decides (R23, R27).
21. **(A2) Prior art.** A2 repairs ProbOS-specific seams, so no outside search was made. One analogue was considered and deferred: an atomic publish through a temp file and rename inside `RecordsStore`, which would change every writer's failure behaviour. `docs/research/reference-projects.md` was not re-examined for a repair amendment.
22. **(A4) Prior art.** `os.walk`'s `onerror` callback (it may raise to abort the walk) is the standard library's error-reporting traversal; 3.12's `Path.rglob` has none, so the strict listing walks with `os.walk` and the default keeps `rglob` (adopted). python-frontmatter recognises the YAML delimiter only on a line of its own (`FM_BOUNDARY = re.compile(r"^-{3,}\s*$", re.MULTILINE)`, `frontmatter/default_handlers.py`). That is the right fix for `_parse_document`, deferred to its own BF because it changes how every Ship's Records reader parses a document holding `---` (R25). Python's `re` documents that `[a-z]` with IGNORECASE matches four letters outside ASCII, and that `(?a:...)` scopes ASCII matching to a group (adopted for the section names only). Terminal escape injection through stored text is a known class; refusing C0 and C1 controls at the one parser closes it for notes. Unicode format characters can still reorder how a note displays and are deferred (R26). `docs/research/reference-projects.md` has no row on file listing, frontmatter or terminal-safe text (A4-AV4).
23. **(A4) Blind spots.** A late-returning write's note is `written` and promotable: true, by design. A cancelled stand-down reports nothing, and its notes stay (R27). A cut-off write's orphaned `git add` thread can contend for the index lock with the next write (pre-existing, R23). Python 3.13's `glob` may bind `os.scandir` at import, so C3e asserts the default listing's result only for the native denial.
24. **(A5) Prior art and blind spots.** The standard library's walkers each decide some errors for the caller. `os.walk` passes `scandir` errors to `onerror` but files an entry whose `is_dir()` raises as a non-directory. 3.12's `Path.walk` and the `*.md` selector under `rglob` swallow every `OSError` (the orchestrator's reading of `Lib/os.py:386-399` and `Lib/pathlib.py:191-215`, `:1112-1156`, 3.12.13). A strict reader therefore owns its traversal: an explicit `os.scandir` loop, one table, and a trace-and-fault test that fails for an operation without a row (adopted; rounds 2 and 3 each found one instance of this class). `pathlib`'s `exists()` and `is_file()` read EBADF, ELOOP, ENOENT, ENOTDIR and three Windows errors as "not there" (`_ignore_error`), so every existence question in the strict read was replaced (O5 to O7). Considered and deferred: a create-only write in `RecordsStore` (R28), and a strict `pending` review (R31). No outside search: this is ProbOS-specific plumbing, and `docs/research/reference-projects.md` was not re-examined for a repair amendment.

## 14. Diff Reviewer: properties to verify

1. `parse_lesson` returns a `LessonLearned` only when the four sections appear once each, in order, each non-empty and together at most 700 characters (A2; property 14). `LessonLearned.render` produces text that `parse_lesson` returns unchanged. A `Cites:` line is never part of a section, and text before the first heading never is either.
2. `parse_citations` returns only ids that `offered` maps from a handle in a `Cites:` line: each once, in order of first mention, at most 12. Nothing the agent typed other than a handle becomes an id.
3. `_exit_note_record` never raises for any document. It returns a record only when the envelope (version 1, non-blank timeline, callsign, agent type and DID, at most 12 distinct non-blank ids), the path (`exit_note_path` of the envelope's timeline and agent type), the author (the callsign), the body (the origin line, then a lesson in the format) and the classification (`ship` or `fleet`) all hold. The record's timeline is the envelope's, and it carries the DID, agent type, callsign and ids.
4. `plan_promotion` sends every `exit-notes/` document through `_exit_note_record` and nothing else, and appends it to `withheld` when that returns None. Every other source is handled exactly as before.
5. `exit_note_citations` applies the same `_exit_note_record` rule and counts a note only while `source_state` says CREATED, or for every valid note when the archive is None. Like `plan_promotion`, it skips unread a listed document that `source_kind_for` does not class as an exit note (frontmatter not a mapping), so a document the promotion can never archive never makes the read raise (C3c). It writes nothing, and propagates any read failure.
6. `run_stand_down` asks each member at most once. It never asks a member with no DID or callsign, one whose note already exists in this timeline, or one whose turn begins after the window closes. It bounds each ask by the turn limit and the remaining window and cancels it on timeout. A turn whose ask times out, fails, comes late, declines or leaves no lesson writes nothing; a write that fails or is cut off after publishing leaves its note and is reported with its path (A4, A5). It runs at most `concurrency` turns at once and serialises Ship's Records writes (S6, S6b). A written note's body is exactly `exit_note_body(...)` of the parsed lesson.
7. `stand_down_vessel` refuses, asking nobody, when the archive is disabled, Ship's Records is absent, or the instance id is blank or `"unknown"`. It addresses only `is_crew_agent` agents, sending each a `direct_message` from `"captain"` with `session` False through `intent_bus.send`, and treats a None or unsuccessful result as no reply. `stand_down.py` imports nothing from `probos.knowledge.archive_*`.
8. `/stand-down` is in the shell's help and dispatch, and is in `_BLOCKED_COMMANDS`, so `_handle_slash_command` answers before touching the runtime.
9. Every AD-754 entry point checks the pending-note citations before anything is erased: `forget_episode` before attachments, and `_forget_all` before its first erase. Both come before the attachment unlink and the audit marking (X1b). S3's archive check still runs first at every entry point. A refusal erases nothing and carries only paths. With `exit_note_citations=None` the behaviour is byte-identical to S3's.
10. `/forget` reads citations once, before building the manager, only from a real `RecordsStore` and only while `config.archive.enabled` is True. It passes S3's archive only when it is a real `ArchiveStore`, and answers 409 `exit_notes_cite_erased_episodes` with the paths, logging the count only. `exit_note_citations` and `ExitNotesBlockErasure` are imported in `src` only by `routers/security.py`.
11. The new tests use the real parser, Ship's Records, promotion, review, archive, `EpisodicMemory`, `ErasureManager`, app route, `probos archive veto`, `probos reset` and Oracle. The stand-ins are the agent's model (a stub `ask`, or a stub bus subscriber), the in-memory episodic store in M2, an identity stub returning real `IdentityRef`s, and S1's config loader. Every store lies under `tmp_path`.
12. (A2, A4, A5) `RecordsStore.list_entries(strict=True)` raises every `OSError` of 7.3a's O1 to O5 except a missing `directory`'s, which lists nothing; otherwise it lists exactly what the default lists, in the same order (C3f); `strict=False` runs the same `rglob` call as before for every caller. `exit_note_citations` and `run_stand_down` pass `strict=True`; `plan_promotion` does not.
13. (A2) A `direct_message` with `bounded_turn: True` makes `_conversational_agentic_will_run` return False and changes nothing else; no other sender sets it. The stand-down sets it on every turn.
14. (A2) `parse_lesson` accepts nothing whose rendering would parse differently, nothing with a NUL or a lone surrogate, and nothing over 700 characters in all. `_exit_note_record` requires an `int` version 1, provenance within `exit_note_provenance_ok`, episode ids within `is_exit_note_text`, and a body equal to `exit_note_body` of its parsed lesson.
15. (A2) `run_stand_down`: the window starts before the first read; each turn has one deadline its recall and ask share and its reply must meet; a billet is claimed before asking, and its path is re-read under the write lock; no write begins once the window has closed (the existence check, without an await, charged first), a write still awaiting is cut off by the window, nothing is ever removed, and a failed or cut-off write reports the path of any note it left; a member's exception is that member's `FAILED`; on any `BaseException` every turn is cancelled and drained before it re-raises. (A5) A first read that returns after the window closes refuses before any turn task is created.
16. (A5) Every filesystem operation of the strict read appears in 7.3a's table with one disposition, and no failure yields a shorter list. `_markdown_files_or_raise` has one `except` clause (O1, O2); every other `OSError` propagates; it returns `[]` only for a missing root; it calls nothing on the filesystem but `os.scandir` and `DirEntry.is_dir(follow_symlinks=False)` (C3g's trace). `list_entries(strict=True)` raises any `OSError` of a listed file's read. `exit_note_citations` raises for a `ship` or `fleet` listed note `read_entry` cannot find. The stand-down's `_present` reads only `FileNotFoundError` and `NotADirectoryError` as absent; its guard writes nothing on unknown, and `_left_at` names the path on unknown. Everything outside the table is in R31.
17. (A5) `cmd_stand_down` prints the count of `written` turns and, apart, the number of `failed` or `timed_out` turns that carry a path; `TurnOutcome`'s docstring says such a path may hold a note, not that it does.
18. (A5) `_stored_text` returns `str(value or "")`, and `""` only on `ValueError`. It serves every stored frontmatter value the promotion converts (`_title_for`; S1's author and metadata; the exit note's metadata), and nothing else that is archived changes.

## 15. Acceptance criteria

1. The exit-notes window gives each crew agent one bounded turn, keeps what it writes, and lets the reset continue when the time runs out or an agent writes nothing (S1 to S8, S10; D-1 to D-9).
2. Exit notes are archived at the reset with the author's DID and callsign and the ids of the episodes they cite, attributed to the generation that wrote them, and labelled as inherited for a later crew (P1, S15; P-1 to P-9, D-12).
3. No raw episode is ever written to the archive. A note is the agent's lesson and its origin line; the service copies no episode text, and citations are ids (S1, S14; `SourceKind` still has no episode member, K1).
4. The lessons format (Observation, Discussion, Lesson, Recommendation) is validated by one parser at the stand-down and at the promotion (L1 to L3, P2; L-1 to L-9).
5. The Captain reviews notes before they are archived and vetoes any of them with S3's tools (C4, X2).
6. An AD-754 erasure never leaves the next reset to archive a note citing an erased episode, and erases nothing (attachments and audit rows included) while it refuses (X1, X1b, X2, X4, C3c; E-1 to E-6, R-1 to R-6, P-12).
7. `/stand-down` runs only at the Captain's console (S13; H-1, A-1).
8. Every test in §6 fails on its milestone's base as named, and every row in §10 is killed by the named test. One broad gate and one PR for M1 to M4; cross-family review of M1, M2 and M3 (HIGH).
9. (A2) A stand-down turn is answered inline or not at all: no tool-calling loop, background promotion or task outlives it, and no other DM behaves differently (S16, S7d; G-1, D-32, D-33).
10. (A2, A4, A5) No failure of a filesystem operation of the strict read (7.3a's table, O1 to O7) clears an AD-754 erasure or lets a stand-down write over a note. Only a missing root, a billet not found at the stand-down's check, and bytes that are not UTF-8 read as absent (C3d to C3i, X8, S8c, S8d, S2c; RS-1, RS-4, RS-6 to RS-10, P-14, P-16, D-21, D-42 to D-44, D-46).
11. (A2) A whole note at every bound reaches a later crew through the real Oracle tool, and every lesson the parser accepts is stored and archived exactly as the Captain reviewed it (L6, L1b, P2; L-2, L-10, L-15, P-6).
12. (A2, A4) The window bounds the first read, and no write begins after it closes; the stand-down removes nothing, and every note a failed or cut-off write left is reported with its path; one billet, one turn (S2b, S4c, S4d, S4e, S8b; D-20, D-22 to D-25, D-37, D-38). A5: a first read that returns after the window refuses before any turn is created, and the console counts a write that may have left a note apart from a completed one (S4f, S13d; D-45, C-3).
12a. (A4) Every value the exit-note rule admits survives Ship's Records, every episode offered can be cited by a note the promotion archives, and a note the rule refuses is withheld without raising, the real reset included (P4, S7e, L8, L10, P2; L-17, L-18, D-36, P-15).
12b. (A5) A stored frontmatter value that `str()` cannot convert never stops a plan or a reset; it is archived as no value (P5, P6; P-17 to P-19).
13. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**R1.** Chain-of-command review of lessons (#1569 comment 1, item 3: department chief, then the Counselor or XO) is not built. S4's notes reach canon through the Captain's opt-out review only (D12). S5 owns it, with the after-action reports. The Captain may overrule the ordering.

**R2.** The `/forget` route reads pending-note citations once per request. A note written after that read and before the erase is not checked (X7 pins the bound). Both are actions on one vessel. A per-episode re-read would close it at the cost of a Ship's Records scan per episode.

**R3.** S3's R3 (a promotion landing between an erasure's checks) stays with S5. S4 promotes only at the offline reset, under the AD-816 pidfile, which excludes the running vessel and so `/forget`.

**R4.** A tier 2 reset deletes every episode with the crew, including those an exit note cites (`chroma.sqlite3`, `episode_archive.db`). An archived lesson's `source_episode_ids` are provenance identifiers from then on, and S3's archive check has no live episode to protect until S5's continuous promotion archives lessons while their episodes live. Then AD-1340 S5's retention has something to keep.

**R5.** Ship's Records keep exit notes across a tier 2 reset, so a later crew's Oracle records tier (keyword search, `oracle_service.py:1058-1071`) can return a note without S2's archive label. The origin line ("... for their successor. A record, not a memory.") is the mitigation; S2's RS2-6 is the general gap.

**R6.** No HXI surface for the stand-down; it is console-only (`_BLOCKED_COMMANDS`). An HXI route would need the Captain's authentication on a long-running operation.

**R7.** The stand-down's bounds (180 s, 900 s, concurrency 2, 12 episodes, 160 characters) are module constants, not `config.py` fields.

**R8.** `EpisodicMemory.recent_for_agent` reads the whole ChromaDB collection on each call and blocks the event loop. A stand-down makes one call per crew agent.

**R9.** The exit-note path is keyed by agent type (D7). Two crew agents of one type share their billet's path: the first in crew order (agent type, then agent id) takes the turn and the second is `duplicate`, not asked (A2, M2-3). A later stand-down asks the first again, so a billet's second crew agent never gets its own turn. Keying notes by agent would give one note per agent; that is S5's choice.

**R10.** `config/ontology/records.yaml` (`repository_structure`) does not list `exit-notes/`; `tests/test_ontology_records.py:143` pins seven directories.

**R11.** A timed-out turn is cancelled inside the agent's DM chain (System QA's precedent). Each asked agent records the stand-down exchange, including the episode excerpts it was shown, in its own episodic memory, as it records any 1:1 message. That memory is wiped at the reset.

**R12.** S3's R6 is now reachable: an AD-754 refusal naming N notes needs N `probos archive veto` calls.

**R13.** With the archive enabled but not open, a refusal for notes (fail closed, D16) cannot be cleared from the running vessel. The Captain's veto writes the archive file, and the route cannot read vetoes until the archive opens again (a restart).

**R14.** A Ship's Records document placed at an exit-note path, with a valid envelope, by any writer other than the stand-down (a file-writing tool, a hand edit) is promoted as an exit note, with the citations it lists. This is the trust S1 extends to `reports/convergence/` documents with `author: system`. The Captain's `pending` review shows it. A digest recorded by the stand-down could bind each note to its writer.

**R15.** S3's R8 now covers one more case: if an agent's `run_command` can reach `probos archive veto`, an agent could veto another agent's pending note. Not verified, as S3 left it.

**R16.** BF-939 (#1683, open): an AD-754 erasure unlinks each attachment of the erased episode without asking whether another episode shares the content-addressed blob (S3's R11). With S4, a cited episode can lose a shared blob while its note awaits the reset, if the Captain erases an uncited episode that shares it. S4's guarantee holds: the cited episode is not erased, the note carries ids and never attachment content, and the tier 2 reset then wipes the episode. S4 neither depends on BF-939 nor worsens it. Its tests use episodes with no shared attachment and assert that an attachment survives only for a refused erasure (X1b). BF-939 must land before S5 archives lessons whose cited episodes stay live. Its option (a), keeping bytes the requester asked to erase because another episode holds them, is the Captain's decision there.

**R17.** S3's R13 (the archive citation check reads every citing row once per call, N+1 calls per cascade) is scheduled to S5, not taken here. S4 adds no per-episode read: its check reads Ship's Records once per request and then looks up a mapping. S4's archived citations come one per crew agent per reset and name episodes that reset wipes, so the rows S3's check reads grow by tens per generation, far from R13's measured 10,000. The fix belongs where citing entries become continuous: S5, with an indexed citation table (episode id to entry id; a schema change and a migration). One read per erasure alone is not enough, because S3's E8 needs the per-episode re-read to catch a citation that lands mid-cascade (S3's R3), which S5 also owns.

**R18.** (A2, M2-10; injected-only; regression: neither, verified on `26f3feec`) `shell.py:347`'s generic error fallback renders exception text as Rich markup. Not S4's: the fix (escape in the shared fallback) belongs to the shell.

**R19.** (A2, M3-F2; ordinary reach; regression: neither, reproduced on `e6ced018`) `api.py:439-442` imports `HTMLResponse` locally, so `app.openapi()` raises `PydanticUserError` and `/openapi.json` answers 500 whenever the HXI fallback route is registered (an unbuilt-HXI checkout; where the HXI is built, `api.py:400` mounts `ui/dist` and the fallback is never registered). `test_ad1207_fault_visibility.py:218` already excludes it. Not S4's change surface (S4 edits only `_BLOCKED_COMMANDS`). Already registered as F-141 on #1523 (AD-1340 S2a review round 1, Low, pre-existing); S4 neither repairs nor re-files it (A3). The fix stays one line plus that test's premise.

**R20.** (A2, A4) `plan_promotion`'s listing (`archive_promotion.py:227`) stays non-strict, as S1 built it; A4 keeps it so, and a directory the reset cannot list is passed over, as a file is. A note file unreadable at the reset's moment is skipped, not withheld: tier 2 keeps it for the next reset, and tier 3 deletes Ship's Records and the note with it, unarchived. A strict reset would stop on any unreadable record of any source. The AD-754 read is strict (fail closed), the safe asymmetry.

**R21.** (A2) The passive Oracle context (`OracleService.query_formatted`, `oracle_service.py:763`) previews 300 characters of each entry, for every archive kind. An ORACLE-tier agent receives an exit note passively as its label, title and origin line; the whole note comes through the Oracle tool (L6). Pre-existing for every kind.

**R22.** (A2) Ship's Records' reads and writes run synchronously on the event loop (`list_entries`, `write_entry`'s file write, YAML). The window bounds every await (the first read as a coroutine, the git calls, the semantic indexer), not a synchronous stall inside one. Pre-existing for every records caller (M2's property 6).

**R23.** (A2, rewritten by A4) The stand-down removes nothing. A note a failed or cut-off write published stays in the working tree the promotion reads, and the report gives its path. It may be unstaged, staged or uncommitted in Ship's Records' git history, and missing from AD-1138's semantic index until its next write or backfill. A cut-off write's executor thread (`git add`) can finish after the turn has ended, and can contend for the index lock with the next write, whose `git add` then fails silently (`_git_sync` returns on a non-zero exit) while its file is still on disk. Executor threads cannot be cancelled.

**R24.** (A2, corrected by A4 from round 2's M2-8) A stand-down turn is a `direct_message` on the intent bus, and its reply is read as text (`DmReply.from_intent_result` in `stand_down_vessel`); the DM reply pipeline (`DmReplyPipeline`, built on the HTTP and group reply paths) does not run on it. So reply tags do nothing here. A valid `[NOTEBOOK]` or `[CREATE_TASK]` saves no notebook and opens no work item; it stays literal text in the reply, and in the note when it falls inside a section (round 2's `s4q2-valid-tags-and-unicode-consumers`: no notebook, no work item, the tags in a promotable note). The prompt asks for the notes alone; the rule does not strip tags, and a later crew reads them as text. Running the pipeline here would add work with its own owner and bounds, so it is not done.

**R25.** (A4, R2-F3; ordinary reach; regression: neither, pre-existing) `RecordsStore._parse_document` (`records_store.py:1202-1212`) splits a document at the first two `---` it finds (`raw.split("---", 2)`), inside a frontmatter value too. An author or topic holding `---` reads back cut short, and the rest of the frontmatter lands in the body (round 2: `Normal---Name` reads back as `Normal`). Every Ship's Records reader is affected (`read_entry`, `list_entries`, `search`, `write_entry`'s update in place, `publish`). S4 closes it for exit notes at the rule (`is_exit_note_text` refuses `---`; P4). The fix, a delimiter only on a line of its own (python-frontmatter's `^-{3,}\s*$`), changes how every reader parses such a document and needs a census of the live Ship's Records first. It is its own BF, for the orchestrator to file with the BF ceiling.

**R26.** (A4, the remainder of R2-F5; considered, deferred) Unicode format characters (category Cf: the bidirectional overrides U+202A to U+202E and U+2066 to U+2069, zero-width characters) are accepted in a lesson. A terminal does not act on them, but they can reorder or hide what a note shows the Captain's review. Some are legitimate in scripts the crew may write (ZWJ, ZWNJ). Refusing the bidirectional overrides is one line in `_NOT_LESSON_TEXT` if the Captain wants it.

**R27.** (A4, round 2 M2-3) A stand-down cancelled by the Captain or by the vessel stopping prints no report. Every note it published stays whole in Ship's Records, including the one whose commit was cut short (`write_entry` writes the file before it awaits git), and `probos archive pending` lists them all for review and veto before the reset (S4e). The stand-down does not remove a cancelled write's note: it cannot prove the file is its own without a store change, and the note is the same whole note the agent wrote.

**R28.** (A5, round 3 M2-1; reach reclassified to a writer outside the vessel's event loop racing the write, injected-only; P2; regression: neither, M2's own, reproduced on `e1e97d25`) The stand-down's check of the billet (`_present`, with no await) and `write_entry`'s file write are not one atomic create. `write_entry` is an AD-550 upsert (`records_store.py:299-343`), so a document another process or thread creates at the exact billet path in the sub-millisecond between them is revised (author replaced, revision 2), and the turn reports `written`. No ProbOS writer names the path (A4-AV1). The asked agent has no tools during its turn. Python 3.12's `asyncio.wait_for` awaits the write inline, so no sibling task interleaves. The race is symmetric: a hand edit saved a moment later overwrites the stand-down's note. A create-only keyword on `write_entry` (open with mode `x`, default off) would close the stand-down's side. It changes the one function every Ship's Records writer uses, so it is its own slice, not bundled into R25's BF.

**R29.** (A5, round 3 R3-M1-3; P3, injected-only; regression: neither, a test gap reproduced on `e1e97d25`) L6 budgets a six-digit generation label as the longest; S2's renderer accepts wider generations (int64's maximum renders 80 characters against L6's 67). The note stays whole at today's bounds (1,184 of 1,200 characters at that maximum), so no production truncation is shown. L6 should budget the label the real renderer gives at the largest generation the archive stores.

**R30.** (A5, round 3 M2-5; P3, injected-only: a malformed identity; regression: neither, M2's own) `commands_stand_down.py` prints a refused identity's callsign through Rich `escape`, which removes markup, not terminal controls, so an ESC sequence in a callsign reaches the console. The normal naming ceremony produces none. The fix (encode C0 and C1 controls in every display field) belongs with R18's console hardening, as a separate row.

**R31.** (A5, 7.3a's table) Outside the strict read's table, each decided:
(a) `_safe_path`'s `Path.resolve()` (non-strict `realpath`): an error it raises propagates, and the path it returns is what O1, O5 and O6 open, so their dispositions apply.
(b) The one-snapshot bound (R2).
(c) A root that the OS cannot address (beyond `MAX_PATH` without long-path support) reads as missing, like any absent root. The roots are Ship's Records' own short paths.
(d) A special file (a FIFO, a device) named `*.md` is read as a file, as every listing reads it; no ProbOS writer makes one.
(e) A junction cycle ends in an `OSError` (fail closed).
(f) The default listing (`strict=False`) stays lossy at every operation, and so do the reset's promotion and the Captain's `pending` review built on it (R20). A note unreadable while the Captain reviews is not listed, and a later reset archives it if it reads then.
(g) Bytes that are not UTF-8 are skipped by the strict listing (A2); a document rewritten between the strict listing and the citation read's second read raises there (fail closed).
(h) Git (`_git_sync` returns on a non-zero exit, R23) and `write_entry`'s own `exists()` (R28's window).

**R32.** (round 4 A2; P2, injected-only; present since S1 (`20c1ec00`), regression: neither; decided by the Architect, recorded and not fixed) `_stored_text` (`archive_promotion.py:88-99`) catches only `ValueError`. (1) A hand-edited frontmatter value that is a YAML alias chain deeper than the interpreter's recursion limit loads, and then `str()` raises `RecursionError`, so `plan_promotion` raises and `probos reset` exits 1 with nothing erased (reproduced with a 5,000-deep chain; a 1,200-deep chain does not raise on Python 3.12). (2) An alias graph in which each level references the previous one twice (the "billion laughs" shape) does not raise: `str()` is exponential in time and memory, so the reset hangs. Reach: R14's hand-edit reach (ProbOS's writers dump frontmatter from dicts built in code, `records_store.py:356,479,1100`, and the nine archived fields are scalar strings). The "never raises" claims of `_stored_text` and `_exit_note_record` are false for both cases until this is fixed. **Fix, for the next slice that edits `archive_promotion.py`:** convert only scalar values (`str`, `int`, `float`, `bool`, `datetime.date`), archive any container or other type as no value, and keep the `ValueError` clause; no container is then ever passed to `str()`, which closes both cases by construction, and S1's result changes only for a container-valued field, which no ProbOS writer produces. Tests: cases `[alias-chain-5000, alias-dag-40x2]` in P5 for each field, with a per-case time bound, and one P6 case through the real reset, which must exit 0. Census row: deleting the scalar guard must fail the alias-chain case. Other code that reads frontmatter and calls `str()` or `json.dumps()` on it is the same class and was not enumerated.

**R33.** (round 4 A3; P3, injected-only; a test gap; regression: neither) C3g's tripwire (`tests/test_ad1341_s4_lessons.py:310-327`) covers `os.stat`, `os.lstat`, `os.listdir` and `os.walk`, but not file opens; the production walker makes none (the reviewer's trace and the orchestrator's agree). Fix: add `io.open` (which `Path.open` uses), `os.open` and `builtins.open`, with a control showing that an unlisted open makes C3g fail. Census row: inserting `Path(search_path).open().close()` at the walker's entry must fail C3g.

**R34.** (round 4 B1; P3, injected-only; a test gap) S4f (`tests/test_ad1341_s4_stand_down.py:478-501`) never observes whether a turn task was created; the ordering at `stand_down.py:283-287,422` is correct (the reviewer's control confirms it). Fix: count `_turn` task creations with `loop.set_task_factory` and assert zero, including when the clock equals the deadline (an `asyncio.all_tasks()` snapshot afterwards is not enough: a wrongly created task can finish before it). Census row: moving the check at `:422` (`clock() >= deadline`) after `asyncio.create_task` must fail S4f.

**R35.** (round 4 B2; P3, injected-only; a test gap) S13d (`:1106-1132`) has a single scenario; the check at `commands_stand_down.py:40` is correct. Fix: parametrise the outcomes: `written`, already-written and duplicate turns with a path add no warning; failed and timed-out turns with a path are counted exactly; failed and timed-out turns without a path are not counted; a zero count prints no warning line. Census row: changing the check at `commands_stand_down.py:40` to count every turn that has a path must fail S13d.

**R36.** (round 4 B3; reclassified by the Architect: not a defect) `stand_down.py` imports `Path` only under `TYPE_CHECKING` (`:57-58`), so `typing.get_type_hints(_present)` raises `NameError`. That is the repository's convention (`cognitive/decomposer.py:20-21`, `identity_key_binding.py:73-74`, `startup/fleet_organization.py:17-18`), and no production code calls `get_type_hints` (a search of `src` finds none).

**R37.** (round 4 A1; resolved, no repository change) The "Killed by" cells of §10 may carry parameter globs (`[read-*]`, `[listing-*]` and `[*-stat-ebadf]` in RS-1, RS-4 and RS-6); a consumer of the table must match them as `fnmatch` patterns over the test parameter ids. The orchestrator's census runner (outside the repository) now does, and RS-1, RS-4 and RS-6 are killed with no problem flagged; the 110 of 110 result is the census of record.

## 16. Validation of record (2026-10-26, win32)

The same record as `DECISIONS.md`'s *Validation of record* bullet for AD-1341 S4.

**Mutation campaign.** The 110 rows of §10 (44 for M1, 50 for M2, 16 for M3), one at a time on the assembled tree (tree `1b7874e6f803`, the candidate `4f855b90`: `origin/main` `20c1ec00` plus this contract (A5) and the three milestones and three repairs applied by tool), whole-line mutation, each row run against the tests it names, pytest without `-x`: **110 of 110 killed**; the unmutated baseline over the three new files is 230 passed. The runner first flagged RS-1, RS-4 and RS-6 as claimed-not-failing only because their cells are parameter globs it compared literally (R37); with the glob-aware runner those three rows were re-run on the same tree: killed, no problem. Files mutated, by git blob id: `api.py` `c633a0571148`, `cognitive_agent.py` `8a91253ae635`, `commands_stand_down.py` `410e9df30e68`, `shell.py` `efecadd7b78c`, `archive_promotion.py` `4d38f7762fff`, `erasure.py` `d2afffa507db`, `lessons.py` `ab6f4afbc735`, `records_store.py` `bbda4f0cbbdc`, `routers/security.py` `f0065b65eb9f`, `stand_down.py` `392df829cedc`; tests `test_ad1341_s4_lessons.py` `a7391f46b268`, `test_ad1341_s4_stand_down.py` `5454c540624c`, `test_ad1341_s4_exit_note_erasure.py` `80c78e258b0b`.

**Tests first.** Each new file fails at its first import over the tree before its milestone (§6); the last repair's cases (A5) fail 30 of 230 over the previous candidate's source (`bbc64351`) and pass over this one, with no collection error, among them the served route erasing a cited episode when a directory's type cannot be read.

**Focused lists.** 556, 661 and 534 passed, with one POSIX-only skip (a FIFO) in each of the first two; the three new files alone 230 passed.

**Stress.** The stand-down file 8 of 8 runs, the lessons file and the exit-note file 5 of 5, and the timing cases (S4c, S3c, S4d) 270 of 270 in one process.

**Review.** M1 to M3 by `gpt-6.1-sol` (`max`) in four rounds: round 1 found 24 findings (four P1), round 2 sixteen (two P1 with one root), round 3 nine (one P1: `os.walk` filed an entry whose type it could not read as a file), round 4 six (no P1 and no finding with ordinary reach in production). Amendments A2 to A5 were decided by the Architect, who took the round-three brake twice (continue, then rescope: the round-4 findings are registered as R32 to R36, and R37 records the census runner's glob matching).
