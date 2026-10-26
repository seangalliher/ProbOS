# AD-1341 S4: the lessons format, and the stand-down that gives each crew agent one bounded turn to leave exit notes for its successor

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26

**Header edits (orchestrator, 2026-10-26, mechanical; no pair, SEARCH or REPLACE changed):** the **Base** paragraph (S3 merged: base `origin/main` `20c1ec00`), section 4's "Expected focused counts" paragraph (measured on that base) and its tests-first sentence, and section 6's names of each new test file's first failing import (each leg was run on the oracle).

**Amendment A1:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26, from the orchestrator's dry run of A0 on the S3 candidate `60e4415e`: all 26 pairs applied once; M2 and M3 passed; M1 failed one hidden pin, S1's import census of `archive_promotion.py` (7.4a now updates it). A1 also renames the lesson class to `LessonLearned` (a `Lesson` already exists, `evolution_store.py:73`), records the phantom triage (§12), names BF-939 (#1683) and S3's register R11 and R13 (§0, D16, register R16, R17), and hardens four things S3's round 1 taught: the citation read skips a document the promotion skips (C3c, P-12), the refusal precedes the attachment unlink and the audit marking (X1b, E-5, E-6), the write lock has a test (S6b, D-17), and every refusal and control asserts its own text or premise (S11, X5, X7).

**Status:** build-ready. Slice 4 of 6 of #1569; it does not complete the issue. No new AD or BF number. **Base:** `origin/main` `20c1ec00` (S3 merged as PR #1684; tree `c382d42c5daf0e32f445bb982e4cf4b162f4210e`); the orchestrator re-verified all 27 pairs on it by tool on 2026-10-26 (zero failures). A0 was drafted on the S3 oracle `fefd7f79`; A1 re-verified every anchor on S3's repaired head `60e4415e` (**S3 anchors this contract depends on**). Every SEARCH below anchors on text S3 does not touch, except the two listed in **S3 anchors this contract depends on** (after §11). The orchestrator re-verifies every SEARCH on the real post-S3 merge before any Builder starts; a changed anchor comes back to the Architect. **Captain:** nothing in this slice meets a Captain condition (D18). One decision (D12, chain-of-command review moves to S5) is the Captain's to overrule.

**Milestones and tiers:** M1 the lessons format and the exit note's promotion (**HIGH**: crew-authored text and citations into the Ship's Archive); M2 the stand-down (**HIGH**: it produces the crew-authored text and the citations); M3 the AD-754 window for notes not yet archived (**HIGH**: erasure, privacy); M4 trackers. Each milestone is one Builder delegation and one local commit, built in order. The broad gate is the orchestrator's single canonical run, once, after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1341-s4 --receipt logs/gates/ad1341-s4.receipt.json`. The Builder runs only the focused gates in §4. Review: cross-family (`gpt-6.1-sol`) for M1, M2 and M3 (D17). One mutation campaign, on the assembled tree (§10).

**Tests:** new `tests/test_ad1341_s4_lessons.py` (M1: 17 functions), `tests/test_ad1341_s4_stand_down.py` (M2: 18 functions), `tests/test_ad1341_s4_exit_note_erasure.py` (M3: 8 functions). Updated: `tests/test_ad1341_s1_archive_store.py` (M1: the closed `SourceKind` set) and `tests/test_ad1341_s1_promotion.py` (M1, A1: the service's import set), each with an inline reason.

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
  - **(A) chosen: the Captain's message.** A `direct_message` intent `{"text": prompt, "from": "captain", "session": False}` through `runtime.intent_bus.send`, as `channels/base.py:452-457` sends one, so the agent's own cognition answers. Services run the loop and the crew hold the judgment (AD-1299, AD-1336). The bus's own gates apply: a refusal or a stopped agent returns no turn.
  - (B) a new `exit_notes` intent handled in `CognitiveAgent`: rejected. Agent-side chain changes for one turn per generation.
  - (C) the service calls the model itself in the agent's name: rejected. That is not the agent's judgment and bypasses its standing orders and character.
  - (D) AD-1347 agent work items, (E) the duty schedule or the proactive loop, (F) a Ward Room DM thread: rejected. Each is claimed or fired on its own cadence (`duty_schedule.py:4`, `:173-197`; `agent_work.py:1-24`), and none can bound a window that ends at a reset. The issue named the duty schedule; a cron duty cannot be started by the Captain's order and cannot bound its own end.
- **D4 (what the agent is asked).** `exit_notes_prompt` (7.6), fixed in code and pinned by S9. It says why it asks (the successor will not share the agent's memories), what to write (what it learned, what it would do differently, what remains open), that writing is optional (reply `NO NOTES` and nothing is recorded), the exact format and its bound, the optional `Cites:` line, and where the note goes: Ship's Records under its callsign and DID, the Captain's review and veto, then the Ship's Archive, where every later crew reads it labelled as inherited. It tells the agent to write nothing it would not share with the whole ship, to summarise and not quote its memories, and to reply without tools. It shows the agent at most 12 of its own most recent episodes, each as a handle (`e1`..), a date and at most 160 opening characters.
- **D5 (the bounds).** `STAND_DOWN_TURN_SECONDS = 180.0` per turn (the Captain's own 1:1 messages use a 60-second TTL, `session.py:119`). `STAND_DOWN_WINDOW_SECONDS = 900.0` for the whole stand-down. `STAND_DOWN_CONCURRENCY = 2` turns at once, inside AD-636's 6 concurrent model calls. A turn past its bound is cancelled through `asyncio.wait_for`, as System QA's are. A reply that arrives after the window writes nothing. An agent whose turn has not begun when the window closes is not asked (`not_reached`). The stand-down returns by the end of the window plus cancellation. A slow episode read is bounded by the same turn limit; a failed one offers no episodes. Module constants, not configuration (register R7). Tested: S3 (turn), S4 (window, late reply, not reached), S4b (the window bounds a turn its own bound would allow), S6 (concurrency), S7 (12 episodes, 160 characters).
- **D6 (the format, and where it is validated).** Four sections, in order, each once, each non-empty and at most 1,200 characters. Four full sections render to 4,867 characters, so a note with its origin line and S2's label stays under the Captain's 6,000-character tool result cap and AD-1148 never elides it (L6 pins the bound). Headings may be `## Observation`, `**Observation**`, a bare `Observation` line or `Observation: text`. A label needs its colon, so "Lesson learned, ..." stays text. Text before the first heading is dropped. A `Cites:` line is read separately and never kept. **One parser** (`parse_lesson`) reads the agent's reply at the stand-down and the stored note at the promotion, and `LessonLearned.render` writes the canonical form, which parses back to itself (L1). A reply not in the format writes nothing (`not_in_format`).
- **D7 (where a note waits for the reset).** Ranked:
  - **(A) chosen: a Ship's Records document** at `exit-notes/{timeline}/{agent_type}.md`. The body is a fixed origin line ("Exit notes left by {callsign} ({agent_type}) of the crew of timeline {timeline} for their successor. A record, not a memory.") followed by the rendered lesson. The frontmatter has `author` (the callsign), `classification: ship`, `status: submitted`, `topic`, `tags`, and the envelope `exit_note: {version, timeline_id, callsign, agent_type, author_did, source_episode_ids}`. S1's promotion already reads Ship's Records, and S3's `pending` and `veto` already work by records path, so the Captain reviews and vetoes notes with the tools that exist. The path is keyed by agent type, not callsign, because callsigns repeat across generations (S2's RS2-3).
  - (B) a notebook entry (`notebooks/{callsign}/exit-notes.md`): rejected. Notebooks default to `private`, and S1's notebook criterion needs a `claim_id` or `published`. Exit notes would be mixed with an agent's working notes.
  - (C) a new store under the registry rules: rejected. A new `.db`, a baseline row and backup coverage, and the promotion would need a second reader. Nothing gained.
  - (D) promote straight into the archive at the stand-down: rejected. It skips S3's review, adds an archive writer that runs inside the vessel (S3's R3 race), and breaks S1's rule that the reset promotes before wiping.
- **D8 (classification).** `ship`. A note is written for the next crew, and C1 admits `ship` to the archive. Not `fleet`: fleet sharing is not built. Not narrower: C1 would withhold it, and the note exists to be inherited.
- **D9 (provenance and citations).**
  - The author's DID, callsign and agent type come from `IdentityService.resolve(slot_id)` (AD-441, AD-1346's one resolver). An agent without a DID or callsign is not asked (`no_identity`).
  - Citations are the handles the agent names in its `Cites:` line, mapped to the episodes it was shown. Any other handle is dropped, and a note cites at most 12 distinct ids. So a note can cite only the agent's own recent episodes, and never an id it typed.
  - The service never copies an episode's text into a note. The note is the origin line plus the lesson the agent wrote. S1 shows an agent's words may restate what it remembers, and the prompt says to summarise, not quote.
  - The entry is attributed to **the timeline that wrote the note** (the envelope's), not the reset that promotes it. A note left by a skipped promotion is promoted at a later reset and still labelled as the generation that wrote it (P1, P3).
- **D10 (what reaches the archive, and when).** At the reset's promotion, under S1's rule: `probos reset` promotes before it wipes, and its plan now includes `exit-notes/` documents. The dry run lists them, and S3's `pending` shows each note's state. A note that breaks the rule is withheld and reported, never raised, so one bad note cannot stop a reset (S1 A3's lesson). The record carries `source_episode_ids`: the first non-empty citations in the archive.
- **D11 (idempotence).** A note already present at its path in this timeline is never overwritten. A second `/stand-down` in one generation asks only the agents without a note (`already_written` for the rest), so a stand-down cut short by its window can be finished without asking anyone twice. S1's key `(kind, ref, sha256)` makes a second promotion of an unchanged note PRESENT under any timeline (P3).
- **D12 (does a lesson need approval, and who approves).** Ranked by what stays in the delegated-authority envelope:
  - **(A) chosen: opt-out review by the Captain, as S3 built it.** `probos archive pending` lists each note before the reset, the note is a readable Markdown file, and `probos archive veto PATH --reason TEXT` keeps one out. S1's default (promote before the reset) is unchanged. The Captain sits at the top of the chain of command, so the issue's "review before canon" holds at its last stage. No new control, flag or schema.
  - (B) chain-of-command review (#1569 comment 1, item 3: the department chief, then the Counselor or XO): **moved to S5**, with the after-action reports. There, lessons arrive continuously and a review step has a natural home (a dream step or duty). Inside a stand-down it would double the model turns in a bounded window whose reviewers are themselves writing their own notes, and a review not finished when the window closes would block or lose the note. **The Captain may overrule** this ordering. It moves a review stage the Captain asked for to the next slice; it does not weaken a control (register R1).
  - (C) opt-in approval behind a default-off flag (S3's D2 B): rejected for S4. A flag nobody turns on is dead code. With it on, a `--full` reset would delete unapproved notes with Ship's Records, because S6's snapshot is not built (S3's D2 B reason).
- **D13 (the Captain's controls).** `/stand-down` reports each agent's outcome and its note's path, then the next steps (`probos archive pending`; `probos archive veto PATH --reason TEXT`; stop the vessel; `probos reset`). Notes are read as files under `ship-records/exit-notes/{timeline}/`. A veto is S3's: content-free, permanent, honoured by the promotion with any content.
- **D14 (the AD-754 window).** Ranked:
  - **(A) chosen: refuse while a pending note cites a matched episode.** The `/forget` route reads `exit_note_citations` once per request, before anything is erased. A note counts while S3's `source_state` says the next promotion would archive it (CREATED). A vetoed, erased or already archived note does not count; an already archived one is S3's own check. `ErasureManager` raises `ExitNotesBlockErasure(paths)` before anything is erased (a single episode, before its attachments; a scan, at the top of `_forget_all`), and the route answers 409 with the paths. The Captain vetoes each note and retries. Same shape as S3's D8: nothing is erased silently, and the open route gains no writer.
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
| D3 | S12 (a real intent bus, `direct_message` from the Captain, never a non-crew agent, a refused turn writes nothing) |
| D4 | S9 |
| D5 | S3, S4, S4b, S6, S7 |
| D6 | L1, L2, L3, L6; the one-parser rule by P2 `[body-not-in-format]` and S2 `[not-in-format]` |
| D7, D8, D9 | S1, S12, P1, P2, S7, S7b |
| D10 | P1, P2, S15 |
| D11 | S8, P3 |
| D12, D13 | C4, X2 |
| D14 | X1, X2, X3, X7 (the bound), C1, C2 |
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

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write each milestone's new test file first and run it on the milestone's base. It must fail at import (§6 names the error). §6's last column (the assertion each test fails at once the names exist but the behaviour is the base's) is the Architect's analysis, not a run you can make: do not try to reach it. If a test outside §7 fails, stop and report it; never delete or loosen a test.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** the format and the exit note's promotion | HIGH | 7.1 new `src/probos/knowledge/lessons.py`; 7.2 `src/probos/knowledge/archive_store.py`; 7.3 `src/probos/knowledge/archive_promotion.py`; 7.4 `tests/test_ad1341_s1_archive_store.py`; 7.5 new `tests/test_ad1341_s4_lessons.py` | `tests/test_ad1341_s4_lessons.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s2_inherited_label.py tests/test_ad1341_s3_veto_store.py tests/test_ad1341_s3_review_cli.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad524_ships_archive.py tests/test_records_store.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M2** the stand-down | HIGH | 7.6 new `src/probos/stand_down.py`; 7.7 new `src/probos/experience/commands/commands_stand_down.py`; 7.8 `src/probos/experience/shell.py`; 7.9 `src/probos/api.py`; 7.10 new `tests/test_ad1341_s4_stand_down.py` | `tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s3_erasure_cascade.py tests/test_shell.py tests/test_experience_commands.py tests/test_ad700a_diagnostic_slash_command.py tests/test_bf914_channel_allow_lists.py tests/test_callsign_routing.py tests/test_bf877_unapproved_design_is_refused.py tests/test_ad1053_actionable_notifications.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M3** the AD-754 window | HIGH | 7.11 `src/probos/knowledge/erasure.py`; 7.12 `src/probos/routers/security.py`; 7.13 new `tests/test_ad1341_s4_exit_note_erasure.py` | `tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad1341_s3_review_cli.py tests/test_erasure_manager.py tests/test_ad1340_s1_erasure.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_bf905_erasure_live_scan.py tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2b_restore_route.py tests/test_ad1025b_path_anchoring.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M4** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

M1 adds `exit_note_citations` and tests it (C1 to C3c). Its consumer, the route, arrives in M3.

**Expected focused counts (measured by the orchestrator on the real base `20c1ec00`, replacing A1's figures, which predate S3's repair):** M1 480 passed, 1 skipped. M2 397 passed, 1 skipped. M3 403 passed. (A1's figures were M1 458, M2 388, M3 393.) No list changes: M1's list already holds `tests/test_ad1341_s1_promotion.py` (7.4a), and M2's and M3's hold `tests/test_ad1341_s3_erasure_cascade.py` (X1b imports its `_traced` and `_traces`).

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `SourceKind.EXIT_NOTE` (`"exit_note"`) | `promote_entry` (stored as `source_kind` and `category`); `source_state`, `veto_source` (S3); `_pending_label` and `probos archive veto` (print `record.source_kind.value`); S1's closed-set pin (7.4) | a new kind; no column change |
| `source_kind_for` returns `EXIT_NOTE` for `exit-notes/` | `plan_promotion` (its one caller in `src`, Absence S4-AV3) | notes enter the plan |
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
| L3 | `test_a_reply_not_in_the_format_is_no_lesson[...7 cases]` | D6: missing, reordered, repeated, empty, over 1,200, prose, not text | (new module) |
| L4 | `test_a_declining_reply_is_recognised_and_nothing_else_is[...8]` | D4 | (new module) |
| L5 | `test_citations_name_only_the_episodes_offered[...6]` | D9: only offered handles, once each, in order | (new module) |
| L5b | `test_a_lesson_cites_at_most_the_bounded_number_of_episodes` | D9: 12 | (new module) |
| L6 | `test_the_section_bound_keeps_a_full_note_and_its_label_inside_the_tool_result_cap` | D6's disclosed bound: 4,867; label + note under 6,000 | (new module) |
| L7 | `test_an_exit_note_has_one_path_per_timeline_and_agent_type` | D7: the slug rule; ValueError for no letter or digit | (new module) |
| P1 | `test_an_exit_note_is_promoted_with_its_own_provenance` | D9, D10: the row's timeline (the note's, not the reset's), kind, title, content, author type, callsign, DID, citations, classification | `promoted.created == (path,)` (base: an `exit-notes/` path is no source) |
| P2 | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing[...11 cases]` | D6, D9, D10: each break withheld; the plan never raises; the citation read counts none | `plan.withheld == (path,)` |
| P3 | `test_an_exit_note_is_archived_once_whichever_reset_promotes_it` | D11 | `first.created == (path,)` |
| C1 | `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it[new, vetoed, erased, present, uncited, no-archive]` | D14, D16: one rule; fail closed with no archive | `cited == expected` |
| C2 | `test_a_veto_between_the_citation_read_and_the_promotion_decides_both` | D14, the case that changes the state between the two reads | `before == {...}` |
| C3 | `test_the_citation_read_raises_when_ship_s_records_cannot_be_listed` | D14: a failed read is never "no citations" | `pytest.raises(OSError)` |
| C3b | `test_ship_s_records_without_exit_notes_cite_nothing` | the empty case, and the missing `exit-notes/` directory | (new function) |
| C3c | `test_a_document_the_promotion_skips_is_never_read_as_a_citing_note` | A1, D14's one rule: frontmatter that is not a mapping; the promotion skips it unread, and so does the citation read | (new function; on A0's code: `AttributeError` from `read_entry`) |
| C4 | `test_the_captain_s_review_lists_an_exit_note_as_a_source_to_be_promoted` | D12, D13: S3's review sees the note | `[...] == [(path, PromotionOutcome.CREATED)]` |
| K1 | `tests/test_ad1341_s1_archive_store.py::test_source_kinds_are_closed_and_none_is_an_episode` (updated) | the closed set gains `exit_note`; none is an episode | the set equality (base: no `exit_note`) |
| K2 | `tests/test_ad1341_s1_promotion.py::test_the_service_imports_only_the_knowledge_layer` (updated, A1, 7.4a) | the promotion service still imports only the knowledge layer, now with `probos.knowledge.lessons` | the set equality (base: no `lessons` import, until 7.3 pair 2) |

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

**M3, `tests/test_ad1341_s4_exit_note_erasure.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| X1 | `test_an_erasure_a_pending_exit_note_cites_erases_nothing[episode, agent, resource]` | D14: a real `EpisodicMemory`; nothing erased; the path named | `pytest.raises(ExitNotesBlockErasure)` |
| X1b | `test_a_refused_erasure_for_a_note_keeps_the_cited_episodes_attachment_and_audit_row[episode, agent, resource]` | A1, S3's finding M3-F1 asked of this check: S3's real `FilesystemAttachmentStore` and `AuditLog` (`_traced`); the refusal precedes the unlink and the audit marking | `pytest.raises(ExitNotesBlockErasure)` |
| X2 | `test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes[episode, agent]` | **the real seam:** real stand-down → real `/forget` 409 with the path, nothing erased → the Captain's real `probos archive veto` → retry 200 → the real `probos reset` archives no note | `refused.status_code == 409` (base: 200) |
| X3 | `test_a_note_the_next_reset_would_not_archive_with_this_citation_blocks_nothing[vetoed, erased, present, uncited, another-episode]` | D14 | (passes once the keyword exists: the control) |
| X4 | `test_the_check_fails_closed_while_the_archive_is_enabled_but_not_open[enabled-not-open, disabled]` | D16: S3's R2 for notes | `answer.status_code == 409` |
| X5 | `test_the_forget_route_reads_notes_only_from_a_real_records_store` | the route tests' `MagicMock` runtime is no records store; its premise (A1) shows a real store's read counts the note | (passes on the base: the control; kills R-3) |
| X6 | `test_only_the_forget_route_reads_exit_note_citations_and_only_the_manager_refuses_on_them` | census | `_importers("exit_note_citations") == {"routers/security.py"}` |
| X7 | `test_a_note_written_after_the_request_read_its_citations_does_not_stop_it` | D14's disclosed bound: one read per request (register R2); its premise (A1) shows a second read counts the late note | (passes once the keyword exists: the control) |

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

#: The longest section, in characters. Four full sections render to 4,867 characters, so an exit note with its origin
#: line and its Ship's Archive label stays under the 6,000-character tool result cap (AD-1148) and is never elided.
LESSON_SECTION_MAX_CHARS: Final = 1200

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
_SECTION = "(observation|discussion|lesson|recommendation)"
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
_DECLINED = re.compile(r"^\W*no notes\W*$", re.IGNORECASE)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


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

    The four sections must each appear once, in order, each non-empty and at most ``LESSON_SECTION_MAX_CHARS``
    characters. A heading is a markdown heading (``## Observation``), the name alone on its line (``**Observation**``,
    ``Observation``) or a label with a colon (``Observation: text``). Text before the first heading is not part of the
    lesson and is dropped. A ``Cites:`` line belongs to ``parse_citations`` and is never part of a section.
    """
    if type(text) is not str:
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
    if any(not body or len(body) > LESSON_SECTION_MAX_CHARS for body in bodies):
        return None
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
    EXIT_NOTE_KEY,
    EXIT_NOTE_VERSION,
    EXIT_NOTES_DIR,
    LESSON_MAX_CITATIONS,
    exit_note_header,
    exit_note_path,
    parse_lesson,
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

    The rule: the ``exit_note`` envelope (version 1) names a timeline, a callsign, an agent type and the author's DID,
    and lists at most ``LESSON_MAX_CITATIONS`` distinct episode ids; the path is the one ``exit_note_path`` gives for
    that timeline and agent type; the author is the callsign; the body is the note's origin line followed by a lesson
    in the format; the classification is ``ship`` or ``fleet`` (C1). The entry is attributed to the timeline that wrote
    the note, not to the reset that promotes it, so a note a skipped promotion left behind keeps its own generation.

    Never raises for a document: every value ``PromotionRecord`` would refuse is checked here first, so one bad note is
    withheld and never stops a reset (S1 A3's rule). The one rule for the promotion and for ``exit_note_citations``.
    """
    if type(document) is not dict or type(document.get("frontmatter")) is not dict:
        return None
    frontmatter, content = document["frontmatter"], document.get("content")
    envelope = frontmatter.get(EXIT_NOTE_KEY)
    if type(envelope) is not dict or envelope.get("version") != EXIT_NOTE_VERSION:
        return None
    named = [envelope.get(field) for field in ("timeline_id", "callsign", "agent_type", "author_did")]
    if any(type(value) is not str or not value.strip() for value in named):
        return None
    note_timeline, callsign, agent_type, author_did = named
    cited = envelope.get("source_episode_ids")
    if type(cited) is not list or any(type(item) is not str or not item.strip() for item in cited):
        return None
    if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):
        return None
    try:
        expected_path = exit_note_path(note_timeline, agent_type)
    except ValueError:
        return None
    if path != expected_path or frontmatter.get("author") != callsign:
        return None
    header = exit_note_header(callsign, agent_type, note_timeline)
    if type(content) is not str or not content.startswith(f"{header}\n\n") or parse_lesson(content) is None:
        return None
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
        metadata={
            "status": str(frontmatter.get("status") or ""),
            "record_created": str(frontmatter.get("created") or ""),
            "record_updated": str(frontmatter.get("updated") or ""),
        },
    )


async def exit_note_citations(records: RecordsStore, archive: ArchiveStore | None) -> dict[str, tuple[str, ...]]:
    """AD-1341 S4 (D14): each episode id cited by an exit note the next promotion would archive, with those notes.

    The notes are read as the promotion reads them (``_exit_note_record``, the one rule). With an open archive a note
    counts while ``source_state`` says CREATED; a vetoed, erased or already archived note does not (an archived one
    is S3's own check). With no open archive every valid note counts (fail closed: the next reset opens the archive
    and would promote it). Reads Ship's Records and the archive; writes nothing; any failure propagates.
    """
    citing: dict[str, list[str]] = {}
    for listed in await records.list_entries(EXIT_NOTES_DIR):
        path = listed["path"]
        if source_kind_for(path, listed["frontmatter"]) is not SourceKind.EXIT_NOTE:
            continue  # plan_promotion skips it unread (frontmatter not a mapping), so it can never be archived
        record = _exit_note_record(path, await records.read_entry(path, ARCHIVE_READER))
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

import json
from pathlib import Path
from typing import Any

import pytest

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
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_VERSION,
    LESSON_MAX_CITATIONS,
    LESSON_SECTION_MAX_CHARS,
    LESSON_SECTIONS,
    LessonLearned,
    exit_note_body,
    exit_note_header,
    exit_note_path,
    exit_notes_directory,
    is_declined,
    parse_citations,
    parse_lesson,
)
from probos.knowledge.records_store import RecordsStore
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _NEXT_SHIP, _SHIP, _data_dir, _records

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
        content=exit_note_body(callsign, agent_type, timeline, _LESSON) if content is None else content,
        message=f"test: exit notes of {callsign}",
        classification=classification,
        status=EXIT_NOTE_STATUS,
        topic=f"Exit notes of {callsign}",
        tags=["exit-notes", "ad-1341"],
        extra_frontmatter={EXIT_NOTE_KEY: fields} if with_envelope else None,
    )
    return note_path


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


_NOT_LESSONS: dict[str, object] = {
    "missing": "\n\n".join(f"## {name}\n\n{body}" for name, body in _sections()[:3]),
    "reordered": "\n\n".join(f"## {name}\n\n{body}" for name, body in (_sections()[1], _sections()[0], *_sections()[2:])),
    "repeated": f"{_LESSON.render()}\n\n## Lesson\n\nAnd once more.",
    "empty-section": "## Observation\n\n## Discussion\nd\n## Lesson\nl\n## Recommendation\nr",
    "too-long": LessonLearned("o" * (LESSON_SECTION_MAX_CHARS + 1), "d", "l", "r").render(),
    "prose": "I learned a great deal on this voyage, and I leave it all to my successor.",
    "not-text": 42,
}


@pytest.mark.parametrize("case", sorted(_NOT_LESSONS))
def test_a_reply_not_in_the_format_is_no_lesson(case: str) -> None:
    assert parse_lesson(_NOT_LESSONS[case]) is None


@pytest.mark.parametrize(
    "reply, declined",
    [
        (DECLINE_REPLY, True), ("No notes.", True), ("**NO NOTES**", True), ("", True), ("   \n", True),
        ("No notes on the coolant yet, but here they are.", False), (_LESSON.render(), False), (None, False),
    ],
    ids=["exact", "punctuation", "bold", "empty", "blank", "a-sentence", "a-lesson", "not-text"],
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


def test_the_section_bound_keeps_a_full_note_and_its_label_inside_the_tool_result_cap() -> None:
    full = LessonLearned(*("x" * LESSON_SECTION_MAX_CHARS for _name in LESSON_SECTIONS))

    assert parse_lesson(full.render()) == full
    assert len(full.render()) == 4867
    assert parse_lesson(LessonLearned("x" * (LESSON_SECTION_MAX_CHARS + 1), "d", "l", "r").render()) is None
    body = exit_note_body("C" * 24, "a" * 32, "t" * 64, full)
    label = "[Inherited from the crew of generation 999999: not your own memory]"
    assert len(label) + 1 + len(body) <= 6000  # the Captain's tool_result_max_chars: AD-1148 never elides a note


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
}


@pytest.mark.parametrize("case", sorted(_BROKEN))
async def test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, **_BROKEN[case])

    plan = await plan_promotion(records, timeline_id=_SHIP)  # never raises: a bad note is withheld

    assert plan.records == ()
    assert plan.withheld == (path,)
    assert await exit_note_citations(records, None) == {}


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


async def test_a_document_the_promotion_skips_is_never_read_as_a_citing_note(tmp_path: Path) -> None:
    """A1: frontmatter that is not a mapping. ``plan_promotion`` skips the document unread, so it can never be
    archived; the citation read skips it too, instead of raising in ``read_entry`` and stopping every erasure."""
    records = _records(_data_dir(tmp_path))
    stray = records.repo_path / exit_note_path(_SHIP, "surgeon")
    stray.parent.mkdir(parents=True)
    stray.write_text("---\nnot a mapping\n---\nCites: ep-000\n", encoding="utf-8")

    plan = await plan_promotion(records, timeline_id=_SHIP)

    assert (plan.records, plan.withheld) == ((), ())  # premise: the promotion skips it
    assert await exit_note_citations(records, None) == {}


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
own most recent episodes by handle. Writing is optional.

No agent can hold a reset. Each turn is bounded by ``STAND_DOWN_TURN_SECONDS``, the whole stand-down by
``STAND_DOWN_WINDOW_SECONDS``, and at most ``STAND_DOWN_CONCURRENCY`` turns run at once. A turn that runs out of time
is cancelled, and a turn that ends late, fails or is never reached writes nothing. ``probos reset`` neither waits for
a stand-down nor needs one.

A note is a Ship's Records document at ``exit_note_path(timeline, agent_type)``, written with the author's callsign,
agent type and DID, the ids of the episodes it cites (only episodes the agent was shown), ``ship`` classification and
status ``submitted``. A note already written in this timeline is never overwritten, so a second stand-down asks only
the agents without one. The reset's promotion archives each note before anything is wiped
(``probos.knowledge.archive_promotion``); the Captain reviews the notes with ``probos archive pending`` and may veto any
of them first. This module never writes the Ship's Archive and never copies an episode's text into a note.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from probos.dm_reply import DmReply
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_VERSION,
    LESSON_MAX_CITATIONS,
    LESSON_SECTION_MAX_CHARS,
    exit_note_body,
    exit_note_path,
    exit_notes_directory,
    is_declined,
    parse_citations,
    parse_lesson,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
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
EPISODE_EXCERPT_CHARS: Final = 160


@dataclass(frozen=True)
class CrewMember:
    """One crew agent as the stand-down addresses it. ``did`` and ``callsign`` are empty when no identity resolves."""

    agent_id: str
    agent_type: str
    sovereign_id: str = ""
    did: str = ""
    callsign: str = ""


class TurnOutcome(StrEnum):
    """What one agent's stand-down turn came to. Only WRITTEN wrote anything."""

    WRITTEN = "written"
    DECLINED = "declined"
    NOT_IN_FORMAT = "not_in_format"
    NO_REPLY = "no_reply"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_REACHED = "not_reached"
    ALREADY_WRITTEN = "already_written"
    NO_IDENTITY = "no_identity"


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


def _offer(episodes: Sequence[Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    """The handles an agent may cite (``e1`` -> an episode id) and the lines that show them (D4, D9).

    The agent's own most recent episodes, at most ``STAND_DOWN_EPISODES``, each by handle, date and at most
    ``EPISODE_EXCERPT_CHARS`` opening characters. An episode without an id, or seen twice, is skipped.
    """
    offered: dict[str, str] = {}
    shown: list[str] = []
    for episode in episodes:
        if len(offered) >= STAND_DOWN_EPISODES:
            break
        episode_id = getattr(episode, "id", None)
        if type(episode_id) is not str or not episode_id.strip() or episode_id in offered.values():
            continue
        handle = f"e{len(offered) + 1}"
        offered[handle] = episode_id
        stamp = getattr(episode, "timestamp", 0.0)
        day = time.strftime("%Y-%m-%d", time.gmtime(stamp)) if type(stamp) in (int, float) and stamp > 0 else "undated"
        excerpt = " ".join(str(getattr(episode, "user_input", "") or "").split())[:EPISODE_EXCERPT_CHARS]
        shown.append(f"{handle} {day}: {excerpt}")
    return offered, tuple(shown)


def exit_notes_prompt(callsign: str, shown: Sequence[str]) -> str:
    """AD-1341 S4 (D4): the Captain's message for one agent's turn: why, what, that it is optional, where it goes."""
    episodes = "\n".join(shown) if shown else "(none could be read)"
    return (
        f"Captain to {callsign}: the crew is standing down before a reset. Your successor in this billet will not share "
        "your memories. This is your one turn to leave them exit notes: what you learned, what you would do "
        "differently, and what remains open.\n\n"
        f"Writing is optional. To decline, reply exactly {DECLINE_REPLY} and nothing is recorded.\n\n"
        "If you write, reply in exactly this form, from your own experience, each section at most "
        f"{LESSON_SECTION_MAX_CHARS} characters:\n"
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
    episodes. Returns when every turn has ended: by ``window_seconds`` after it starts, plus the cancellation of the
    turns still running then. Raises ``StandDownRefused`` when the timeline is missing or names no records path, and
    ``ValueError`` for a bound that is not positive; nothing that happens in a turn raises.
    """
    if type(timeline_id) is not str or not timeline_id.strip():
        raise StandDownRefused("This vessel has no instance id, so its exit notes could not be attributed to a timeline.")
    if concurrency < 1 or turn_seconds <= 0 or window_seconds <= 0:
        raise ValueError("AD-1341 S4: a stand-down's bounds must be positive")
    try:
        directory = exit_notes_directory(timeline_id)
    except ValueError as exc:
        raise StandDownRefused(f"The instance id cannot name a records path: {exc}") from exc
    existing = {listed["path"] for listed in await records.list_entries(directory)}
    deadline = clock() + window_seconds
    gate = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()  # one Ship's Records write at a time: the repository has one git index

    async def _ask_and_write(member: CrewMember, path: str) -> TurnResult:
        try:
            episodes = await asyncio.wait_for(recall(member), timeout=max(0.001, min(turn_seconds, deadline - clock())))
        except Exception:  # log-and-degrade: the turn offers no episodes, so its note cites none
            logger.warning(
                "AD-1341 S4: %s's recent episodes could not be read; its turn offers none", member.callsign,
                exc_info=True,
            )
            episodes = ()
        offered, shown = _offer(episodes)
        remaining = deadline - clock()
        if remaining <= 0:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        prompt = exit_notes_prompt(member.callsign, shown)
        try:
            reply = await asyncio.wait_for(ask(member, prompt), timeout=min(turn_seconds, remaining))
        except TimeoutError:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        except Exception:  # log-and-degrade: one agent's failed turn never stops the others, or the reset
            logger.warning(
                "AD-1341 S4: %s's exit-notes turn failed; nothing is written", member.callsign, exc_info=True,
            )
            return _turn_result(member, TurnOutcome.FAILED)
        if clock() > deadline:  # a reply after the window writes nothing
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        if reply is None:
            return _turn_result(member, TurnOutcome.NO_REPLY)
        if is_declined(reply):
            return _turn_result(member, TurnOutcome.DECLINED)
        lesson = parse_lesson(reply)
        if lesson is None:
            return _turn_result(member, TurnOutcome.NOT_IN_FORMAT)
        cited = parse_citations(reply, offered)
        envelope = {
            "version": EXIT_NOTE_VERSION,
            "timeline_id": timeline_id,
            "callsign": member.callsign,
            "agent_type": member.agent_type,
            "author_did": member.did,
            "source_episode_ids": list(cited),
        }
        async with write_lock:
            try:
                await records.write_entry(
                    author=member.callsign,
                    path=path,
                    content=exit_note_body(member.callsign, member.agent_type, timeline_id, lesson),
                    message=f"AD-1341 S4: exit notes of {member.callsign}",
                    classification="ship",  # AD-1341 S4 (D8): for the next crew, so ship-wide; C1 admits it to the archive
                    status=EXIT_NOTE_STATUS,
                    topic=f"Exit notes of {member.callsign}",
                    tags=["exit-notes", "ad-1341"],
                    extra_frontmatter={EXIT_NOTE_KEY: envelope},
                )
            except Exception:  # log-and-degrade: the turn is reported failed; the other notes are still written
                logger.warning(
                    "AD-1341 S4: %s's exit note could not be written to Ship's Records", member.callsign,
                    exc_info=True,
                )
                return _turn_result(member, TurnOutcome.FAILED)
        return _turn_result(member, TurnOutcome.WRITTEN, path)

    async def _turn(member: CrewMember) -> TurnResult:
        if not member.did.strip() or not member.callsign.strip():
            return _turn_result(member, TurnOutcome.NO_IDENTITY)
        try:
            path = exit_note_path(timeline_id, member.agent_type)
        except ValueError:
            return _turn_result(member, TurnOutcome.NO_IDENTITY)
        if path in existing:
            return _turn_result(member, TurnOutcome.ALREADY_WRITTEN, path)
        async with gate:
            if clock() >= deadline:  # the window closed before this agent's turn began
                return _turn_result(member, TurnOutcome.NOT_REACHED)
            return await _ask_and_write(member, path)

    turns = await asyncio.gather(*(_turn(member) for member in crew))
    report = StandDownReport(timeline_id=timeline_id, turns=tuple(turns))
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
            params={"text": text, "from": "captain", "session": False},
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
import json
import re
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
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.experience.commands import commands_stand_down
from probos.experience.shell import ProbOSShell
from probos.identity_service import IdentityRef
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTES_DIR,
    LESSON_SECTION_MAX_CHARS,
    LESSON_SECTIONS,
    exit_note_body,
    exit_note_path,
)
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.stand_down import (
    EPISODE_EXCERPT_CHARS,
    STAND_DOWN_CONCURRENCY,
    STAND_DOWN_TURN_SECONDS,
    CrewMember,
    StandDownRefused,
    TurnOutcome,
    exit_notes_prompt,
    run_stand_down,
    stand_down_vessel,
)
from probos.types import Episode, IntentMessage, IntentResult
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
from tests.test_ad1341_s4_lessons import _DID, _LESSON

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
    report = await _run(records, (_member(),), ask, turn_seconds=0.2, window_seconds=60.0)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert time.monotonic() - started < 3.0
    assert cancelled.is_set()  # the turn is cancelled, never left running
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
    report = await _run(records, (_member(),), ask, turn_seconds=60.0, window_seconds=0.3)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert time.monotonic() - started < 3.0
    assert await _notes(records) == []


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


def test_the_prompt_says_writing_is_optional_and_what_the_note_is_for() -> None:
    prompt = exit_notes_prompt("Chapel", ("e1 2026-10-25: the coolant alarm cleared again",))

    for phrase in (
        "Captain to Chapel",
        "Your successor in this billet will not share your memories",
        "what you learned, what you would do differently, and what remains open",
        "Writing is optional",
        f"reply exactly {DECLINE_REPLY} and nothing is recorded",
        f"each section at most {LESSON_SECTION_MAX_CHARS} characters",
        *(f"## {name}\n" for name in LESSON_SECTIONS),
        "Cites: (optional)",
        "kept in Ship's Records under your callsign and DID",
        "The Captain may review them and veto them",
        "archived in the Ship's Archive at the reset, where every later crew can read them",
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
    runtime, _received = _vessel(
        _config(tmp_path), _records(data_dir), MockEpisodicMemory(), replies={"surgeon": ("Chapel", _reply())},
    )
    output = StringIO()

    await commands_stand_down.cmd_stand_down(runtime, Console(file=output, width=200), "")

    text = output.getvalue()
    assert f"Chapel: written -> {exit_note_path(_SHIP, 'surgeon')}" in text
    assert "probos archive pending" in text and "probos archive veto PATH --reason TEXT" in text
    runtime.config.archive.enabled = False
    refused = StringIO()
    await commands_stand_down.cmd_stand_down(runtime, Console(file=refused, width=200), "")
    assert "Stand-down refused" in refused.getvalue()


def test_the_stand_down_never_writes_the_ship_s_archive() -> None:
    tree = ast.parse((_SRC / "stand_down.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
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
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.knowledge.archive_promotion import exit_note_citations, plan_promotion
from probos.knowledge.archive_store import PromotionOutcome, SourceKind, VetoOutcome
from probos.knowledge.erasure import ErasureManager, ExitNotesBlockErasure
from probos.stand_down import CrewMember, TurnOutcome, run_stand_down
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _config, _data_dir, _records, _reset
from tests.test_ad1341_s3_erasure_cascade import _traced, _traces
from tests.test_ad1341_s3_review_cli import _veto
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


async def _stand_down(records: Any, *, cites: str = "e1", shown: int = 0) -> str:
    """A real stand-down in which agent-a is shown one of its episodes (``_CITED`` by default) as e1."""

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply(cites)

    async def recall(member: CrewMember) -> list[Any]:
        return [_episodes()[shown]]

    report = await run_stand_down((_AGENT,), ask=ask, recall=recall, records=records, timeline_id=_SHIP)
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


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
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


async def test_a_note_written_after_the_request_read_its_citations_does_not_stop_it(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        citations = await exit_note_citations(records, None)  # the route's one read, before any note exists
        assert citations == {}
        path = await _stand_down(records)  # a note citing _CITED lands after the read
        assert await exit_note_citations(records, None) == {_CITED: (path,)}  # a second read would count it

        result = await _manager(rig.em, citations).forget_episode(_CITED)

        assert result.deleted_episode_ids == [_CITED]  # the disclosed bound: one read per request (register R2)
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

**AD-1341 S4 (2026-10-26), #1569 slice 4 of 6 -- the lessons format, and the stand-down that gives each crew agent one bounded turn to leave exit notes for its successor.** A lesson has four sections, Observation, Discussion, Lesson and Recommendation (#1569 comment 1). One parser (`knowledge/lessons.py`) reads an agent's reply and the stored note, each section at most 1,200 characters, so a note with its label stays under the 6,000-character tool result cap. The Captain types `/stand-down` at the vessel's console (console only: the HXI chat and the channel adapters refuse it), and each crew agent gets one Captain's message through the intent bus, showing it up to 12 of its own recent episodes by handle. Writing is optional (`NO NOTES`). A turn is bounded at 180 s and the whole window at 900 s, with at most two turns at once; a late, failed or unreached turn writes nothing, and `probos reset` neither waits for nor needs a stand-down. A note is a Ship's Records document at `exit-notes/{timeline}/{agent_type}.md`: an origin line ("... A record, not a memory.") and the lesson, `ship` classification, and an `exit_note` envelope with the author's DID, callsign, agent type and the ids of the episodes it cites (only episodes it was shown; no episode text). A second stand-down asks only the agents without a note. The reset's promotion archives each note as `SourceKind.EXIT_NOTE`, attributed to the timeline that wrote it, with the archive's first real `source_episode_ids`; a malformed note is withheld, never raised. The Captain reviews notes with `probos archive pending` and vetoes one with `probos archive veto PATH`. An AD-754 erasure (`POST /api/security/forget`) whose matched episodes a note awaiting promotion cites erases nothing and answers 409 `exit_notes_cite_erased_episodes` with the paths, and fails closed when the archive is enabled but not open; the Captain vetoes the note and retries. Chain-of-command review of lessons moves to S5. Open before S5 and not S4's: BF-939 (#1683, an erasure unlinks an attachment another episode shares) and an indexed citation read for S3's N+1 check. No schema, flag, config field, event type or API route. New: `src/probos/knowledge/lessons.py`, `src/probos/stand_down.py`, `src/probos/experience/commands/commands_stand_down.py`, `tests/test_ad1341_s4_lessons.py`, `tests/test_ad1341_s4_stand_down.py`, `tests/test_ad1341_s4_exit_note_erasure.py`. The contract is `prompts/ad-1341-s4-lessons-and-stand-down.md`.
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
- *D2-D5 (the stand-down).* `probos reset` runs with the vessel stopped, so the turn is a live step before it: `/stand-down` at the console, console only because the HXI chat and the channel adapters reach slash commands without the Captain's console. Each crew agent gets one Captain's `direct_message` through the intent bus, so its own cognition answers; a duty, agent work item or Ward Room thread cannot bound a window that ends at a reset. 180 s a turn, 900 s in all, two at once; a late, failed or unreached turn writes nothing. The bounds are constants.
- *D6-D11 (the note).* One parser for the reply and the stored note; four sections of at most 1,200 characters. A Ship's Records document at `exit-notes/{timeline}/{agent_type}.md` at `ship` classification, so S1's promotion and S3's review and veto handle it unchanged. Provenance from `IdentityService`; citations only of episodes the agent was shown; never episode text. The entry is attributed to the timeline that wrote the note. A note is never overwritten, so a second stand-down asks only the agents without one.
- *D12 (approval).* Opt-out review by the Captain, as S3 built it. Chain-of-command review (#1569 comment 1, item 3) moves to S5 with the after-action reports, because inside a bounded stand-down its reviewers are writing their own notes and an unfinished review would block or lose a note. The Captain may overrule this ordering.
- *D14, D16 (AD-754).* The erasure refuses while a note awaiting promotion cites a matched episode, read once per request with the promotion's own rule; the Captain vetoes the note and retries. Withholding at the reset through the eviction audit was rejected (best-effort writes, can be disabled). S3's R2 is decided fail-closed for notes. S3's R3 stays with S5, because S4 promotes only at the offline reset under the pidfile. S3's R11 (BF-939, #1683, shared attachment blobs) and R13 (an N+1 citation read) are scheduled before S5: S4's citations are notes read once per request, and its archived citations name episodes the same reset wipes.
- *Disclosed effects.* `SourceKind` gains `exit_note` (TEXT column; schema v1). The promotion plan, the dry run and `pending` list notes, and a malformed one is counted as withheld. `/forget` can answer 409 for notes. A stand-down spends at most one model turn per crew agent, and each agent records the exchange in its own episodic memory.
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
- The DM path, the cognitive chain, the proactive loop, the duty schedule, AD-1347, the intent bus and the identity registries.
- No new flag, `EventType`, API route, config field or `.db` file; `user_version` stays 1. `config/ontology/records.yaml` is not edited (register R10).
- Out of scope (D19): S5's after-action reports, continuous promotion and chain-of-command review; S6's `--full` snapshot, description entry and clean slate; fleet sharing; an HXI stand-down; lifting a veto; bulk vetoes.

## 10. Mutation rows (52 rows: 21 for M1, 19 for M2, 12 for M3; whole stripped lines, each occurring once in its file after §7)

One campaign on the assembled tree (M1 to M3 applied), after an unmutated baseline run of the three new test files that passes. Run each row against the named tests and restore the file before the next row. R-1 and R-2 mutate the same line, and so do R-3 and R-4, and E-1, E-5 and E-6; restore between them.

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| L-1 | M1 | `src/probos/knowledge/lessons.py` | `if tuple(name for name, _lines in sections) != LESSON_SECTIONS:` | `if False:` | `test_a_reply_not_in_the_format_is_no_lesson` |
| L-2 | M1 | `src/probos/knowledge/lessons.py` | `if any(not body or len(body) > LESSON_SECTION_MAX_CHARS for body in bodies):` | `if any(not body for body in bodies):` | `test_a_reply_not_in_the_format_is_no_lesson`, `test_the_section_bound_keeps_a_full_note_and_its_label_inside_the_tool_result_cap` |
| L-3 | M1 | `src/probos/knowledge/lessons.py` | `elif _CITES_LINE.match(line):` | `elif False:` | `test_the_four_sections_are_read_in_each_heading_form` |
| L-4 | M1 | `src/probos/knowledge/lessons.py` | `return not stripped or _DECLINED.match(stripped) is not None` | `return not stripped` | `test_a_declining_reply_is_recognised_and_nothing_else_is` |
| L-5 | M1 | `src/probos/knowledge/lessons.py` | `episode_id = offered.get(f"e{int(number)}")` | `episode_id = offered.get(f"e{int(number)}", f"e{int(number)}")` | `test_citations_name_only_the_episodes_offered` |
| L-6 | M1 | `src/probos/knowledge/lessons.py` | `if episode_id is not None and episode_id not in cited and len(cited) < LESSON_MAX_CITATIONS:` | `if episode_id is not None:` | `test_citations_name_only_the_episodes_offered`, `test_a_lesson_cites_at_most_the_bounded_number_of_episodes` |
| L-7 | M1 | `src/probos/knowledge/lessons.py` | `return f"{exit_notes_directory(timeline_id)}/{_slug(agent_type, 'agent_type')}.md"` | `return f"{EXIT_NOTES_DIR}/{_slug(agent_type, 'agent_type')}.md"` | `test_an_exit_note_has_one_path_per_timeline_and_agent_type` |
| L-8 | M1 | `src/probos/knowledge/lessons.py` | `if not slug:` | `if False:` | `test_an_exit_note_has_one_path_per_timeline_and_agent_type` |
| L-9 | M1 | `src/probos/knowledge/lessons.py` | `rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*:\s*{_EMPHASIS}\s*(.*)$", re.IGNORECASE,` | `rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*:?\s*{_EMPHASIS}\s*(.*)$", re.IGNORECASE,` | `test_a_rendered_lesson_parses_back_to_itself`, `test_the_four_sections_are_read_in_each_heading_form` |
| P-1 | M1 | `src/probos/knowledge/archive_promotion.py` | `return SourceKind.EXIT_NOTE  # AD-1341 S4: every exit note is a source; _exit_note_record withholds a bad one` | `return None` | `test_an_exit_note_is_promoted_with_its_own_provenance`, `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it` |
| P-2 | M1 | `src/probos/knowledge/archive_promotion.py` | `if path.startswith(f"{EXIT_NOTES_DIR}/"):  # AD-1341 S4: an exit note carries its own provenance` | `if False:` | `test_an_exit_note_is_promoted_with_its_own_provenance`, `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-3 | M1 | `src/probos/knowledge/archive_promotion.py` | `if type(envelope) is not dict or envelope.get("version") != EXIT_NOTE_VERSION:` | `if type(envelope) is not dict:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-4 | M1 | `src/probos/knowledge/archive_promotion.py` | `if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):` | `if False:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-5 | M1 | `src/probos/knowledge/archive_promotion.py` | `if path != expected_path or frontmatter.get("author") != callsign:` | `if False:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-6 | M1 | `src/probos/knowledge/archive_promotion.py` | `if type(content) is not str or not content.startswith(f"{header}\n\n") or parse_lesson(content) is None:` | `if type(content) is not str:` | `test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing` |
| P-7 | M1 | `src/probos/knowledge/archive_promotion.py` | `timeline_id=note_timeline,  # AD-1341 S4 (D9): the timeline that wrote the note, not the reset's` | `timeline_id=callsign,` | `test_an_exit_note_is_promoted_with_its_own_provenance` |
| P-8 | M1 | `src/probos/knowledge/archive_promotion.py` | `source_episode_ids=tuple(cited),  # AD-1341 S4: the agent's own episodes, by id; never their text` | `source_episode_ids=(),` | `test_an_exit_note_is_promoted_with_its_own_provenance`, `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it` |
| P-9 | M1 | `src/probos/knowledge/archive_promotion.py` | `author_did=author_did,` | `author_did="",` | `test_an_exit_note_is_promoted_with_its_own_provenance` |
| P-10 | M1 | `src/probos/knowledge/archive_promotion.py` | `if archive is not None and (await archive.source_state(record)).outcome is not PromotionOutcome.CREATED:` | `if False:` | `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it`, `test_a_veto_between_the_citation_read_and_the_promotion_decides_both` |
| P-11 | M1 | `src/probos/knowledge/archive_promotion.py` | `citing.setdefault(episode_id, []).append(path)` | `pass` | `test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it`, `test_a_veto_between_the_citation_read_and_the_promotion_decides_both` |
| P-12 | M1 | `src/probos/knowledge/archive_promotion.py` | `if source_kind_for(path, listed["frontmatter"]) is not SourceKind.EXIT_NOTE:` | `if False:` | `test_a_document_the_promotion_skips_is_never_read_as_a_citing_note` |
| D-1 | M2 | `src/probos/stand_down.py` | `reply = await asyncio.wait_for(ask(member, prompt), timeout=min(turn_seconds, remaining))` | `reply = await ask(member, prompt)` | `test_a_turn_that_runs_past_its_bound_is_cancelled_and_writes_nothing`, `test_the_window_bounds_a_turn_its_own_bound_would_allow` |
| D-2 | M2 | `src/probos/stand_down.py` | `if clock() > deadline:  # a reply after the window writes nothing` | `if False:` | `test_the_window_closes_on_time_and_writes_nothing_late_or_unreached` |
| D-3 | M2 | `src/probos/stand_down.py` | `if clock() >= deadline:  # the window closed before this agent's turn began` | `if False:` | `test_the_window_closes_on_time_and_writes_nothing_late_or_unreached` |
| D-4 | M2 | `src/probos/stand_down.py` | `gate = asyncio.Semaphore(concurrency)` | `gate = asyncio.Semaphore(len(crew) + 1)` | `test_no_more_than_the_bounded_number_of_turns_run_at_once` |
| D-5 | M2 | `src/probos/stand_down.py` | `if path in existing:` | `if False:` | `test_a_second_stand_down_asks_only_the_agents_without_a_note` |
| D-6 | M2 | `src/probos/stand_down.py` | `cited = parse_citations(reply, offered)` | `cited = ()` | `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance`, `test_a_note_cites_only_episodes_the_agent_was_shown` |
| D-7 | M2 | `src/probos/stand_down.py` | `if is_declined(reply):` | `if False:` | `test_writing_is_optional_and_a_turn_that_leaves_no_lesson_writes_nothing` |
| D-8 | M2 | `src/probos/stand_down.py` | `classification="ship",  # AD-1341 S4 (D8): for the next crew, so ship-wide; C1 admits it to the archive` | `classification="department",` | `test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance` |
| D-9 | M2 | `src/probos/stand_down.py` | `if not member.did.strip() or not member.callsign.strip():` | `if False:` | `test_an_agent_without_an_identity_is_not_asked` |
| D-10 | M2 | `src/probos/stand_down.py` | `if len(offered) >= STAND_DOWN_EPISODES:` | `if False:` | `test_a_note_cites_only_episodes_the_agent_was_shown` |
| D-11 | M2 | `src/probos/stand_down.py` | `excerpt = " ".join(str(getattr(episode, "user_input", "") or "").split())[:EPISODE_EXCERPT_CHARS]` | `excerpt = " ".join(str(getattr(episode, "user_input", "") or "").split())` | `test_a_note_cites_only_episodes_the_agent_was_shown` |
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

The heading's count includes R-2 and R-4.

Rows with no mutation:

- `_offer`'s duplicate-id skip, and `_ask_and_write`'s write failure: no supported caller produces a duplicate id or a failing write in a test without injection. They are logged and covered by S1's and S2's outcomes.
- (A1) The stand-down's write lock now has a row, D-17: S6b holds each write open, so an unserialised second write overlaps it.
- P-3's `wrong-version` is also an envelope `version` the stand-down never writes.

Mutant D-1 takes 5 s to be killed (the stub's sleep); every other row is killed in under a second.

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

**S4-AV3.** CLAIM: `source_kind_for` has one caller in `src`.
RUN: Grep `source_kind_for` in `src`.
FOUND: `archive_promotion.py:43` (definition), `:117`, `:124` (`plan_promotion`).
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
| Size | `lessons.py` about 175 lines; `archive_promotion.py` +90; `stand_down.py` about 330; `commands_stand_down.py` about 50; `erasure.py` +35; `security.py` +40; the tests about 330, 460 and 290 |

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

## 14. Diff Reviewer: properties to verify

1. `parse_lesson` returns a `LessonLearned` only when the four sections appear once each, in order, each non-empty and at most 1,200 characters. `LessonLearned.render` produces text that `parse_lesson` returns unchanged. A `Cites:` line is never part of a section, and text before the first heading never is either.
2. `parse_citations` returns only ids that `offered` maps from a handle in a `Cites:` line: each once, in order of first mention, at most 12. Nothing the agent typed other than a handle becomes an id.
3. `_exit_note_record` never raises for any document. It returns a record only when the envelope (version 1, non-blank timeline, callsign, agent type and DID, at most 12 distinct non-blank ids), the path (`exit_note_path` of the envelope's timeline and agent type), the author (the callsign), the body (the origin line, then a lesson in the format) and the classification (`ship` or `fleet`) all hold. The record's timeline is the envelope's, and it carries the DID, agent type, callsign and ids.
4. `plan_promotion` sends every `exit-notes/` document through `_exit_note_record` and nothing else, and appends it to `withheld` when that returns None. Every other source is handled exactly as before.
5. `exit_note_citations` applies the same `_exit_note_record` rule and counts a note only while `source_state` says CREATED, or for every valid note when the archive is None. Like `plan_promotion`, it skips unread a listed document that `source_kind_for` does not class as an exit note (frontmatter not a mapping), so a document the promotion can never archive never makes the read raise (C3c). It writes nothing, and propagates any read failure.
6. `run_stand_down` asks each member at most once. It never asks a member with no DID or callsign, one whose note already exists in this timeline, or one whose turn begins after the window closes. It bounds each ask by the turn limit and the remaining window and cancels it on timeout. It writes nothing for a timed-out, failed, late, declined, unparseable or empty turn. It runs at most `concurrency` turns at once and serialises Ship's Records writes (S6, S6b). A written note's body is exactly `exit_note_body(...)` of the parsed lesson.
7. `stand_down_vessel` refuses, asking nobody, when the archive is disabled, Ship's Records is absent, or the instance id is blank or `"unknown"`. It addresses only `is_crew_agent` agents, sending each a `direct_message` from `"captain"` with `session` False through `intent_bus.send`, and treats a None or unsuccessful result as no reply. `stand_down.py` imports nothing from `probos.knowledge.archive_*`.
8. `/stand-down` is in the shell's help and dispatch, and is in `_BLOCKED_COMMANDS`, so `_handle_slash_command` answers before touching the runtime.
9. Every AD-754 entry point checks the pending-note citations before anything is erased: `forget_episode` before attachments, and `_forget_all` before its first erase. Both come before the attachment unlink and the audit marking (X1b). S3's archive check still runs first at every entry point. A refusal erases nothing and carries only paths. With `exit_note_citations=None` the behaviour is byte-identical to S3's.
10. `/forget` reads citations once, before building the manager, only from a real `RecordsStore` and only while `config.archive.enabled` is True. It passes S3's archive only when it is a real `ArchiveStore`, and answers 409 `exit_notes_cite_erased_episodes` with the paths, logging the count only. `exit_note_citations` and `ExitNotesBlockErasure` are imported in `src` only by `routers/security.py`.
11. The new tests use the real parser, Ship's Records, promotion, review, archive, `EpisodicMemory`, `ErasureManager`, app route, `probos archive veto`, `probos reset` and Oracle. The stand-ins are the agent's model (a stub `ask`, or a stub bus subscriber), the in-memory episodic store in M2, an identity stub returning real `IdentityRef`s, and S1's config loader. Every store lies under `tmp_path`.

## 15. Acceptance criteria

1. The exit-notes window gives each crew agent one bounded turn, keeps what it writes, and lets the reset continue when the time runs out or an agent writes nothing (S1 to S8, S10; D-1 to D-9).
2. Exit notes are archived at the reset with the author's DID and callsign and the ids of the episodes they cite, attributed to the generation that wrote them, and labelled as inherited for a later crew (P1, S15; P-1 to P-9, D-12).
3. No raw episode is ever written to the archive. A note is the agent's lesson and its origin line; the service copies no episode text, and citations are ids (S1, S14; `SourceKind` still has no episode member, K1).
4. The lessons format (Observation, Discussion, Lesson, Recommendation) is validated by one parser at the stand-down and at the promotion (L1 to L3, P2; L-1 to L-9).
5. The Captain reviews notes before they are archived and vetoes any of them with S3's tools (C4, X2).
6. An AD-754 erasure never leaves the next reset to archive a note citing an erased episode, and erases nothing (attachments and audit rows included) while it refuses (X1, X1b, X2, X4, C3c; E-1 to E-6, R-1 to R-6, P-12).
7. `/stand-down` runs only at the Captain's console (S13; H-1, A-1).
8. Every test in §6 fails on its milestone's base as named, and every row in §10 is killed by the named test. One broad gate and one PR for M1 to M4; cross-family review of M1, M2 and M3 (HIGH).
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**R1.** Chain-of-command review of lessons (#1569 comment 1, item 3: department chief, then the Counselor or XO) is not built. S4's notes reach canon through the Captain's opt-out review only (D12). S5 owns it, with the after-action reports. The Captain may overrule the ordering.

**R2.** The `/forget` route reads pending-note citations once per request. A note written after that read and before the erase is not checked (X7 pins the bound). Both are actions on one vessel. A per-episode re-read would close it at the cost of a Ship's Records scan per episode.

**R3.** S3's R3 (a promotion landing between an erasure's checks) stays with S5. S4 promotes only at the offline reset, under the AD-816 pidfile, which excludes the running vessel and so `/forget`.

**R4.** A tier 2 reset deletes every episode with the crew, including those an exit note cites (`chroma.sqlite3`, `episode_archive.db`). An archived lesson's `source_episode_ids` are provenance identifiers from then on, and S3's archive check has no live episode to protect until S5's continuous promotion archives lessons while their episodes live. Then AD-1340 S5's retention has something to keep.

**R5.** Ship's Records keep exit notes across a tier 2 reset, so a later crew's Oracle records tier (keyword search, `oracle_service.py:1058-1071`) can return a note without S2's archive label. The origin line ("... for their successor. A record, not a memory.") is the mitigation; S2's RS2-6 is the general gap.

**R6.** No HXI surface for the stand-down; it is console-only (`_BLOCKED_COMMANDS`). An HXI route would need the Captain's authentication on a long-running operation.

**R7.** The stand-down's bounds (180 s, 900 s, concurrency 2, 12 episodes, 160 characters) are module constants, not `config.py` fields.

**R8.** `EpisodicMemory.recent_for_agent` reads the whole ChromaDB collection on each call and blocks the event loop. A stand-down makes one call per crew agent.

**R9.** The exit-note path is keyed by agent type. Two crew agents of one type share a path, and the second is reported `already_written`.

**R10.** `config/ontology/records.yaml` (`repository_structure`) does not list `exit-notes/`; `tests/test_ontology_records.py:143` pins seven directories.

**R11.** A timed-out turn is cancelled inside the agent's DM chain (System QA's precedent). Each asked agent records the stand-down exchange, including the episode excerpts it was shown, in its own episodic memory, as it records any 1:1 message. That memory is wiped at the reset.

**R12.** S3's R6 is now reachable: an AD-754 refusal naming N notes needs N `probos archive veto` calls.

**R13.** With the archive enabled but not open, a refusal for notes (fail closed, D16) cannot be cleared from the running vessel. The Captain's veto writes the archive file, and the route cannot read vetoes until the archive opens again (a restart).

**R14.** A Ship's Records document placed at an exit-note path, with a valid envelope, by any writer other than the stand-down (a file-writing tool, a hand edit) is promoted as an exit note, with the citations it lists. This is the trust S1 extends to `reports/convergence/` documents with `author: system`. The Captain's `pending` review shows it. A digest recorded by the stand-down could bind each note to its writer.

**R15.** S3's R8 now covers one more case: if an agent's `run_command` can reach `probos archive veto`, an agent could veto another agent's pending note. Not verified, as S3 left it.

**R16.** BF-939 (#1683, open): an AD-754 erasure unlinks each attachment of the erased episode without asking whether another episode shares the content-addressed blob (S3's R11). With S4, a cited episode can lose a shared blob while its note awaits the reset, if the Captain erases an uncited episode that shares it. S4's guarantee holds: the cited episode is not erased, the note carries ids and never attachment content, and the tier 2 reset then wipes the episode. S4 neither depends on BF-939 nor worsens it. Its tests use episodes with no shared attachment and assert that an attachment survives only for a refused erasure (X1b). BF-939 must land before S5 archives lessons whose cited episodes stay live. Its option (a), keeping bytes the requester asked to erase because another episode holds them, is the Captain's decision there.

**R17.** S3's R13 (the archive citation check reads every citing row once per call, N+1 calls per cascade) is scheduled to S5, not taken here. S4 adds no per-episode read: its check reads Ship's Records once per request and then looks up a mapping. S4's archived citations come one per crew agent per reset and name episodes that reset wipes, so the rows S3's check reads grow by tens per generation, far from R13's measured 10,000. The fix belongs where citing entries become continuous: S5, with an indexed citation table (episode id to entry id; a schema change and a migration). One read per erasure alone is not enough, because S3's E8 needs the per-episode re-read to catch a citation that lands mid-cascade (S3's R3), which S5 also owns.
