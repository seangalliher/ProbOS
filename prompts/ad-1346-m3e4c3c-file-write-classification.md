# AD-1346 M3e4c3c (#1604): the classification of the file-write rows under cognitive/

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-01
**Status:** build-ready. **Issue:** #1604 (AD-1346 M3, epic #1601). The third part of M3e4c3 (D252, register R130, R133), cut here at D263. No new AD or BF number (`scripts/ad_ceiling.py`: CEILING AD-1356, from GitHub issue titles). **Tier:** test (M1: fixtures and tests only, no `src` file), docs (M2). Nothing parked.
**Dependencies:** AD-1346 M3e4c3b (`prompts/ad-1346-m3e4c3b-file-write-classification.md`) merged to `origin/main`. The build base is `origin/main` at the AD-1356 S3 and S4 merge `693fef40` (§16, Amendment 2), which follows the M3e4c3b merge `d5f10598`.
**Anchors:** every SEARCH text in §7 and §8 was read on the detached checkout `caabbf5c`: `origin/main` at the M3e4c3a merge `ac82876a` (PR #1732), plus M3e4c3b as built (contract `fd541ef7`, M1 `655ac42c`, M2 `caabbf5c`), in its first review round. M3e4c3b has since merged as `d5f10598` (PR #1733; its tree `6f50c7ad738d` is the gated tree), and the orchestrator re-applied the 10 SEARCH/REPLACE blocks by tool on that merge with 0 failures (§16, Amendment 1). Other work has since merged, and the orchestrator re-based the candidate on the AD-1356 S3 and S4 merge `693fef40` (PR #1744; its tree `1580cfea56b2` is the gated tree) with the two tracker anchors re-measured (§16, Amendment 2). 10 SEARCH/REPLACE blocks (M1 8, M2 2), no new file, 2 regenerated files (M2).
**Contract file:** `prompts/ad-1346-m3e4c3c-file-write-classification.md`.

**Identifiers.**
- Register rows: earlier slices' R10 to R133 and this contract's R134 and R135 are written "register R<n>".
- Tests: WF1 to WF6 (M3e4c3a's and M3e4c3b's; WF6 is renamed here) and the new WF7, in `tests/test_ad1346_admission_file_write_census.py`.
- Mutation rows are EL-<n>. Decisions D263 to D267 follow M3e4c3b's D258 to D262.

**Which text describes the head.**
- **Records of the read commit `caabbf5c`:** the Status and Anchors paragraphs, §1, §11 (Verified Against Codebase, Absence Verified), every line number cited in any section, and every SEARCH text in §7 and §8.
- **The M3e4c3b merge (§16, Amendment 1).** `d5f10598` (PR #1733; its tree `6f50c7ad738d` is the gated tree) differs from the read commit `caabbf5c` in two files: `DECISIONS.md` (M3e4c3b's campaign bullet, one line; the heading after M3e4c3b's entry moves from `:1243` to `:1244`) and `prompts/ad-1346-m3e4c3b-file-write-classification.md` (its amendment A2 deletes two lines of the second Absence entry and adds four lines to its §16; the lines of that file that §11 cites are re-run in Absence Verified). `PROGRESS.md` and every `src`, test and fixture file are the same on the merge as on the read commit, so `PROGRESS.md :3` is unchanged. The 10 SEARCH/REPLACE blocks of §7 and §8 apply by tool on the merge with 0 failures.
- **The AD-1356 S3 and S4 merge (§16, Amendment 2).** `693fef40` (PR #1744; its tree `1580cfea56b2` is the gated tree) follows `d5f10598`. `PROGRESS.md` and `DECISIONS.md` gain other items' entries, so `PROGRESS.md :3` is AD-1356 S3 and S4's paragraph and the heading after M3e4c3b's entry in `DECISIONS.md` is BF-946's (§8 gives both anchors on the merge). `docs/development/ad-ledger-snapshot.json` and `open-ads-report.md` are regenerated, and `src`, test and prompt files that this contract neither edits nor cites changed. `tests/fixtures/ad1346_file_write_census.py` and `tests/test_ad1346_admission_file_write_census.py`, which M1 edits, have the same blobs on the merge as on `d5f10598`. The 10 SEARCH/REPLACE blocks of §7 and §8, with the two tracker SEARCH texts of Amendment 2, apply by tool on the merge with 0 failures.
- **Files M3e4c3b writes that this contract edits or cites:**
  - `tests/fixtures/ad1346_file_write_census.py`: M1-01 (`:135-138`), M1-02 (`:170-200`);
  - `tests/test_ad1346_admission_file_write_census.py`: M1-03 (`:7-9`), M1-04 (`:27-29`), M1-05 (`:45-57`), M1-06 (`:138-149`), M1-07 (`:199-201`), M1-08 (`:241-247`);
  - `PROGRESS.md`: M2-01's SEARCH is the head of AD-1356 S3 and S4's paragraph (`:3` on `693fef40`). `DECISIONS.md`: M2-02's anchor is the heading after M3e4c3b's entry (`:1244` on `693fef40`, BF-946's; M3e4c3b's heading `:1232`);
  - `prompts/ad-1346-m3e4c3b-file-write-classification.md`: cited for D258 to D262, register R132 and R133, and its §10 rows EJ-1, EJ-3, EJ-4, EJ-5 and EJ-7; not edited.
- M3e4c3b's review may move text in these files. Re-read each SEARCH and each cited line on the merged base. If one differs, the Architect sends an amendment; the Builder does not adapt it.
- **Parts that describe the candidate's head and name no commit:** the Milestones and Tests lists, §2 to §6, §8's tracker text, §9, §10, §12, §14 and §15.
- **Text inside each REPLACE** (docstrings, comments, row reasons) is head text.
- Where a record and the candidate differ, re-measure; the record does not bind.

**Milestones:**
- **M1 (test):** the 19 rows under `cognitive/` become `System(SHIP, reason)`; `_UNCLASSIFIED`'s owner becomes `M3e4c3d`; `_CLASSIFIED` gains `cognitive/`; WF1's counter and docstrings move; WF6 is renamed; WF7 is new.
- **M2 (docs):** `PROGRESS.md`, `DECISIONS.md`, and the AD ledger regenerated by its tool.

**Process:**
- Each milestone is one Builder delegation and one local commit. Stage by explicit path, never `git add -A`.
- Commit subjects take the form `AD-1346 M3e4c3c, M<n>: ... (#1604)`.
- One cross-family review (`gpt-6.1-sol`) of M1 against §14.
- One mutation campaign of record on the M1 tree (§10), after an unmutated baseline passes.
- The broad gate runs once, after M2: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1346-m3e4c3c --receipt logs/gates/ad1346-m3e4c3c.receipt.json`.

**Tests:**
- M1: `tests/test_ad1346_admission_file_write_census.py` goes from 6 to 7 `def test_` functions, no parametrised cases.

## 1. Problem

- M3e4c3b left 50 rows of `FILE_WRITE_FILES` `Pending("M3e4c3c")`, unclassified (D258, register R133).
- Register R133 ordered their classification under D239 and D218: the 19 files under `cognitive/` first, then the 31 others.

## 2. Solution

- **The cut (D263).** This slice classifies the 19 rows under `cognitive/` (38 points of the scan). M3e4c3d takes the other 31 (register R135). `_UNCLASSIFIED`'s owner becomes `M3e4c3d`.
- **The classification (D264).** Each of the 19 is `System(SHIP, reason)` by D239; the reason names what the file's writes record. No row becomes `Pending("M3e4d")`; `FILE_AGENT_ATTRIBUTED_SCOPES` does not change.
- **The guards (D265).** `_CLASSIFIED` gains `src/probos/cognitive/`, and WF6 becomes `test_the_classified_directories` with the same body. Two rows write an author-like field (`captured_by`, `designer`) that no `src` call sets. The new WF7 fails if a `src` call outside the idea store passes a `captured_by` keyword, or if a `src` call's function is named `AgentVersion`. WF1's kind counter becomes 1 / 38 / 31 / 2.
- **No check.** Nothing is checked, refused or charged. No `src` file changes.

## 3. Decisions (numbered after M3e4c3b's D258 to D262)

- **D263 The cut** (question 1; follows register R133's order).
  - This slice classifies the 19 rows under `cognitive/`. M3e4c3d takes the other 31 (register R135). `_UNCLASSIFIED`'s owner becomes `M3e4c3d`, which moves the 31 rows' owner in one line.
  - Ranked:
    1. this;
    2. all 50 (129 points and 50 reasons in one review);
    3. a smaller group of `cognitive/` (two WF1 counter moves for one directory).
  - Owner label, ranked: 1. `_UNCLASSIFIED`'s owner `M3e4c3d` (one line); 2. `M3e4c3c` kept (false after this slice); 3. a label per row.
- **D264 The classification** (question 2; applies D239). Every row below is `System(SHIP, ...)`. Points are the scan's names at the lines of §11; a scope is the enclosing function.

  | File | Points (line, scope) | What the writes record | Rule |
  |---|---|---|---|
  | `cognitive/agent_patcher.py` | `:239` `AgentPatcher._patch_skill` | the unlink of the temporary file `tempfile.NamedTemporaryFile` (`:202`) holds the patched source in (`:205`), loaded at `:209` | a delete: no text |
  | `cognitive/builder.py` | `:1762`, `:1770` `_restore_pre_build_files`; `:3483`, `:3504`, `:3687`, `:3694` `execute_approved_build` | `modified`, `change["content"]`, `mod`: a file change's content or its text after replacement; saved bytes written back and created files deleted (`:1749-1773`) | D239: no author id recorded; `BuildSpec` (`:114-124`) has no author field |
  | `cognitive/chain_checkpoint.py` | `:91`, `:92` `ChainCheckpointStore.save`; `:127` `ChainCheckpointStore.delete` | `checkpoint.to_dict()` of a `ChainCheckpoint` (`:37-45`: id, chain name, step, time, running context, reason) | D239: no author field |
  | `cognitive/checkpoint.py` | `:83` `write_checkpoint`; `:106` `delete_checkpoint` | the dict at `:73-81` (checkpoint and DAG ids, `source_text`, times, `node_states`, `dag_json`) | D239: no author key |
  | `cognitive/copilot_adapter.py` | `:386` `seed_session_directory` | each non-empty `content` of the `files` it is passed (`:374-386`) | D239: no author id recorded |
  | `cognitive/dm/artifact_extractor.py` | `:198` `_to_docx_libreoffice` | an HTML wrap (`:194-195`) of the `text` it is passed, in a `tempfile.TemporaryDirectory` (`:196`) | D239: no author id recorded |
  | `cognitive/dream_manifest.py` | `:63`, `:64` `DreamManifest._save` | `self._entries`: a timestamp per episode id and step (`:73-79`) | no text |
  | `cognitive/dreaming.py` | `:1025` `DreamingEngine.dream_cycle` | `old_path.rename(new_path)`: each entry of `others` (`:999`) moved into `old_path.parent / "_archived"` (`:1021-1024`) | a rename: no text (register R130's input) |
  | `cognitive/evidence_collector.py` | `:559` `EvidenceCollector._persist` | the YAML of an `EvidenceObservation` (`:537-549`): behaviour codes, confidence, `reasoning`, `raw_response`, `author_id`, `author_callsign`. `classify_post`'s reasoning is the classifier call's output (`:163-171`); `routers/thread_fanout.py:1447-1453` passes `author_id=thread_id` to `record_observation` | D239: the id names what is observed, not the reasoning's author |
  | `cognitive/peer_observation_monitor.py` | `:584`, `:585` `PeerObservationMonitor._save_state` | a `count` and `last_tier` per `detector::observer` key (`:579-582`) | no text |
  | `cognitive/ready_room/idea_store.py` | `:105`, `:106` `IdeaCaptureStore._save` | each idea's `title`, `body`, `captured_by` (`:93-104`); `capture` takes `captured_by` keyword-only from its caller (`:115-118`) | D239: no `src` call passes `captured_by` outside the file (Absence; held by WF7) |
  | `cognitive/sandbox.py` | `:144` `SandboxRunner.test_agent` | the unlink of the temporary file (`:79-85`) the generated agent's source is loaded from (`:90`) | a delete: no text |
  | `cognitive/scout.py` | `:221` `_save_seen`; `:292` `_scout_step_persist_report` | seen repository names with dates (`:219`); a report of `ScoutFinding`s (`:286-291`; fields `:84-98`) | D239: no author field |
  | `cognitive/self_improvement/versioning.py` | `:145`, `:157` `LocalDiskPersistence.promote` | `record.source_code` and a sidecar holding `designer: {version.designer}` (`:146-156`) of an `AgentVersion` (`:33-44`) | D239: no `src` call builds an `AgentVersion` or calls `.promote` (Absence) |
  | `cognitive/self_mod.py` | `:612` `SelfModificationPipeline.handle_add_skill` | the unlink of the temporary file (`:592-598`) the skill source is loaded from (`:602`) | a delete: no text |
  | `cognitive/session_manager.py` | `:183` `SessionManager.close_session`; `:199` `SessionManager._write` | a `Session` (`:32-43`: ids, platform, `user_id`, `agent_type`, times, tasks, context) and its rename into `archive` (`:180-183`) | D239: no author field |
  | `cognitive/skill_catalog.py` | `:678` `import_skill`; `:814` `_rewrite_frontmatter`; `:843` `remove_skill` | a copied skill directory; ProbOS metadata keys (`:800-810`) added to a SKILL.md frontmatter; a skill directory's removal | D239: none sets an author id |
  | `cognitive/skill_forge.py` | `:262` `SkillForge.forge`; `:317` `SkillForge._write_files` | the files `_parse_files` (`:283-296`) takes from a model call's output (`:265-280`), written under a `tempfile.mkdtemp` staging root (`:210`) that `forge` removes (`:262`) | D239: no author id recorded |
  | `cognitive/swe_harness/tools.py` | `:236` `_locked_native_target`; `:1044` `WriteFileTool.invoke`; `:1170` `EditFileTool.invoke` | `str(content)` (`:1044`); `updated`, the text after one replacement (`:1155`); a target opened `r+b` (`:236`) | D239: no author id recorded |

  - Ranked:
    1. this;
    2. `ready_room/idea_store.py` and `self_improvement/versioning.py` pending for M3e4d. Each writes an author-like field, but no `src` call sets one, and WF3's pattern needs a dict display that maps the constant to a name: `idea_store.py:99` maps it to `i.captured_by`, an attribute, and `versioning.py:151` is an f-string;
    3. `evidence_collector.py` pending for M3e4d (it records `author_id` beside reasoning, but the id names what is observed);
    4. `builder.py` and `swe_harness/tools.py` pending for M3e4d (agents' work products, but each writes text with no author id: register R132).
- **D265 The guards** (question 3).
  - `_CLASSIFIED` gains `src/probos/cognitive/`. WF6's body is unchanged and it is renamed `test_the_classified_directories`, because its old name names one slice. The exemption stays the Ship's Records' row alone, because no `cognitive/` row is pending for M3e4d.
  - WF7: outside `cognitive/ready_room/idea_store.py`, no `src` call passes a `captured_by` keyword, and no `src` call's function, a name or an attribute, is `AgentVersion`. `capture` takes `captured_by` keyword-only. `AgentVersion.designer` has no default.
  - Ranked, directory guard: 1. this; 2. WF6 kept and a second guard for `cognitive/` (WF6's "no `System` row lies elsewhere" fails on the 19 either way); 3. the 38 paths pinned.
  - Ranked, author fields: 1. WF7 as above; 2. WF7 on attribute calls named `capture` and `promote` (`cognitive_agent.py:5406` reads an attribute `promote` of another object); 3. register R134 alone.
- **D266 What a static classification does not see** (question 4). Register R134.
- **D267 Cost** (question 5). No `src` file changes and no `SystemConfig` field.

## 4. Milestones and focused gates

| Milestone | Files | Focused gate |
|---|---|---|
| M1 | `tests/fixtures/ad1346_file_write_census.py`, `tests/test_ad1346_admission_file_write_census.py` | `pytest tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_effect_census.py -n 0`; `pytest tests/test_ad1346_admission_file_write_census.py --collect-only -q -p no:cacheprovider -n 0` (record the count: 7) |
| M2 | `PROGRESS.md`, `DECISIONS.md`; regenerated `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | `python -P scripts/gen_ad_ledger.py`, then `python -P scripts/gen_ad_ledger.py --check`, then `pytest tests/test_ad1184_ad_ledger.py -n 0` |

## 5. Consumers of every value this changes

- **`FILE_WRITE_FILES`** (19 values): WF1, WF3, WF4, WF6. No Python file outside the fixture and the test reads it (§11 Absence).
- **`_UNCLASSIFIED`'s owner:** WF1, through `_kind`.
- **`_CLASSIFIED`:** WF6.

## 6. Tests

| File | M | Cases | What |
|---|---|---|---|
| `tests/test_ad1346_admission_file_write_census.py` | M1 | 6 to 7 | WF1's counter and docstring; WF3's docstring; WF6 renamed; new WF7 |

## 7. The contract

### 7.1 M1

**M1-01** (`tests/fixtures/ad1346_file_write_census.py`)

SEARCH:
```
_AGENT_ATTRIBUTED_FILE: Final = Pending("M3e4d", "agent-attributed (D239, D255): FILE_AGENT_ATTRIBUTED_SCOPES names a scope and its author (register R113)")
_UNCLASSIFIED: Final = Pending("M3e4c3c", "not yet classified under D239 and D218 (register R130)")

#: AD-1346 M3e4c3a (D254, D255): each file whose row is ``Pending("M3e4d")`` -> (a scope that writes a file D239 makes
```
REPLACE:
```
_AGENT_ATTRIBUTED_FILE: Final = Pending("M3e4d", "agent-attributed (D239, D255): FILE_AGENT_ATTRIBUTED_SCOPES names a scope and its author (register R113)")
_UNCLASSIFIED: Final = Pending("M3e4c3d", "not yet classified under D239 and D218 (register R130)")

#: AD-1346 M3e4c3a (D254, D255): each file whose row is ``Pending("M3e4d")`` -> (a scope that writes a file D239 makes
```

**M1-02** (`tests/fixtures/ad1346_file_write_census.py`)

SEARCH:
```
    "src/probos/ward_room/threads.py": System(SHIP, "the Ward Room JSONL archive: prune_old_threads appends copies of the thread and post rows it prunes (D218)"),
    # Not yet classified: M3e4c3c's (register R130, R133).
    "src/probos/attachments/filesystem_store.py": _UNCLASSIFIED,
    "src/probos/attachments/image_budget_store.py": _UNCLASSIFIED,
    "src/probos/audio/tts/resident.py": _UNCLASSIFIED,
    "src/probos/avatars/blender_renderer.py": _UNCLASSIFIED,
    "src/probos/avatars/proposal_history.py": _UNCLASSIFIED,
    "src/probos/avatars/rhubarb_backend.py": _UNCLASSIFIED,
    "src/probos/avatars/telemetry_history.py": _UNCLASSIFIED,
    "src/probos/avatars/vision_proposal_history.py": _UNCLASSIFIED,
    "src/probos/captain_card/card.py": _UNCLASSIFIED,
    "src/probos/cognitive/agent_patcher.py": _UNCLASSIFIED,
    "src/probos/cognitive/builder.py": _UNCLASSIFIED,
    "src/probos/cognitive/chain_checkpoint.py": _UNCLASSIFIED,
    "src/probos/cognitive/checkpoint.py": _UNCLASSIFIED,
    "src/probos/cognitive/copilot_adapter.py": _UNCLASSIFIED,
    "src/probos/cognitive/dm/artifact_extractor.py": _UNCLASSIFIED,
    "src/probos/cognitive/dream_manifest.py": _UNCLASSIFIED,
    "src/probos/cognitive/dreaming.py": _UNCLASSIFIED,
    "src/probos/cognitive/evidence_collector.py": _UNCLASSIFIED,
    "src/probos/cognitive/peer_observation_monitor.py": _UNCLASSIFIED,
    "src/probos/cognitive/ready_room/idea_store.py": _UNCLASSIFIED,
    "src/probos/cognitive/sandbox.py": _UNCLASSIFIED,
    "src/probos/cognitive/scout.py": _UNCLASSIFIED,
    "src/probos/cognitive/self_improvement/versioning.py": _UNCLASSIFIED,
    "src/probos/cognitive/self_mod.py": _UNCLASSIFIED,
    "src/probos/cognitive/session_manager.py": _UNCLASSIFIED,
    "src/probos/cognitive/skill_catalog.py": _UNCLASSIFIED,
    "src/probos/cognitive/skill_forge.py": _UNCLASSIFIED,
    "src/probos/cognitive/swe_harness/tools.py": _UNCLASSIFIED,
    "src/probos/credential_store.py": _UNCLASSIFIED,
```
REPLACE:
```
    "src/probos/ward_room/threads.py": System(SHIP, "the Ward Room JSONL archive: prune_old_threads appends copies of the thread and post rows it prunes (D218)"),
    # AD-1346 M3e4c3c: the ship's (D239, D264).
    "src/probos/cognitive/agent_patcher.py": System(SHIP, "AgentPatcher._patch_skill deletes the temporary file it loaded the patched skill source from: no text"),
    "src/probos/cognitive/builder.py": System(SHIP, "execute_approved_build writes the content, or its text after replacement, with no author id (D239); _restore_pre_build_files restores saved bytes and deletes created files"),
    "src/probos/cognitive/chain_checkpoint.py": System(SHIP, "ChainCheckpointStore.save writes a ChainCheckpoint, which has no author field (D239); delete removes it"),
    "src/probos/cognitive/checkpoint.py": System(SHIP, "write_checkpoint writes the source text, node states and serialized form of a DAG, with no author key (D239); delete_checkpoint removes it"),
    "src/probos/cognitive/copilot_adapter.py": System(SHIP, "seed_session_directory writes the non-empty file contents it is passed into a build session directory, with no author id (D239)"),
    "src/probos/cognitive/dm/artifact_extractor.py": System(SHIP, "_to_docx_libreoffice writes the text it is passed, wrapped as HTML, into a temporary directory for LibreOffice, with no author id (D239)"),
    "src/probos/cognitive/dream_manifest.py": System(SHIP, "DreamManifest._save writes a timestamp for each episode id and step marked processed: no text"),
    "src/probos/cognitive/dreaming.py": System(SHIP, "DreamingEngine.dream_cycle renames each non-primary entry of a consolidated cluster into an _archived directory beside it: no text"),
    "src/probos/cognitive/evidence_collector.py": System(SHIP, "EvidenceCollector._persist writes behaviour codes, a confidence and reasoning, with the author_id it observes (D239)"),
    "src/probos/cognitive/peer_observation_monitor.py": System(SHIP, "PeerObservationMonitor._save_state writes a count and a last tier for each detector and observer pair: no text"),
    "src/probos/cognitive/ready_room/idea_store.py": System(SHIP, "IdeaCaptureStore._save writes the title, body and captured_by of each idea; WF7: no src call outside the file passes captured_by (D239)"),
    "src/probos/cognitive/sandbox.py": System(SHIP, "SandboxRunner.test_agent deletes the temporary file it loaded the generated agent source from: no text"),
    "src/probos/cognitive/scout.py": System(SHIP, "_save_seen writes the repositories seen and their dates, and _scout_step_persist_report a daily report of findings; ScoutFinding has no author field (D239)"),
    "src/probos/cognitive/self_improvement/versioning.py": System(SHIP, "LocalDiskPersistence.promote writes agent source and a sidecar holding the designer of its version; no src call builds an AgentVersion (D239)"),
    "src/probos/cognitive/self_mod.py": System(SHIP, "SelfModificationPipeline.handle_add_skill deletes the temporary file it loaded the skill source from: no text"),
    "src/probos/cognitive/session_manager.py": System(SHIP, "SessionManager._write writes a Session, which has no author field (D239); close_session renames it into archive"),
    "src/probos/cognitive/skill_catalog.py": System(SHIP, "import_skill copies a skill directory, _rewrite_frontmatter adds ProbOS metadata to a SKILL.md frontmatter and remove_skill deletes a skill directory; none sets an author id (D239)"),
    "src/probos/cognitive/skill_forge.py": System(SHIP, "SkillForge._write_files writes the files a model call generated into a temporary staging directory, with no author id (D239); forge removes the directory"),
    "src/probos/cognitive/swe_harness/tools.py": System(SHIP, "WriteFileTool.invoke and EditFileTool.invoke write the text they are passed or edit, with no author id (D239); _locked_native_target opens a target read-write"),
    # Not yet classified: M3e4c3d's (register R130, R133, R135).
    "src/probos/attachments/filesystem_store.py": _UNCLASSIFIED,
    "src/probos/attachments/image_budget_store.py": _UNCLASSIFIED,
    "src/probos/audio/tts/resident.py": _UNCLASSIFIED,
    "src/probos/avatars/blender_renderer.py": _UNCLASSIFIED,
    "src/probos/avatars/proposal_history.py": _UNCLASSIFIED,
    "src/probos/avatars/rhubarb_backend.py": _UNCLASSIFIED,
    "src/probos/avatars/telemetry_history.py": _UNCLASSIFIED,
    "src/probos/avatars/vision_proposal_history.py": _UNCLASSIFIED,
    "src/probos/captain_card/card.py": _UNCLASSIFIED,
    "src/probos/credential_store.py": _UNCLASSIFIED,
```

**M1-03** (`tests/test_ad1346_admission_file_write_census.py`)

SEARCH:
```
- WF1  every file the scan finds is a row of ``FILE_WRITE_FILES`` and every row is one: 72 files (1 pending for
       AD-1346 M3e4d, 19 the ship's, 50 pending for AD-1346 M3e4c3c and 2 command-line), and 207 points counted
       by name.
```
REPLACE:
```
- WF1  every file the scan finds is a row of ``FILE_WRITE_FILES`` and every row is one: 72 files (1 pending for
       AD-1346 M3e4d, 38 the ship's, 31 pending for AD-1346 M3e4c3d and 2 command-line), and 207 points counted
       by name.
```

**M1-04** (`tests/test_ad1346_admission_file_write_census.py`)

SEARCH:
```
- WF6  under the directories AD-1346 M3e4c3b classifies, every row but the Ship's Records' is ``System`` under
       ``SHIP`` with a reason, and no ``System`` row lies elsewhere.
"""
```
REPLACE:
```
- WF6  under the directories AD-1346 M3e4c3b and M3e4c3c classify, every row but the Ship's Records' is ``System``
       under ``SHIP`` with a reason, and no ``System`` row lies elsewhere.
- WF7  outside ``cognitive/ready_room/idea_store.py`` no ``src`` call passes a ``captured_by`` keyword, and no
       ``src`` call's function is named ``AgentVersion``.
"""
```

**M1-05** (`tests/test_ad1346_admission_file_write_census.py`)

SEARCH:
```
_RECORDS = "src/probos/knowledge/records_store.py"
#: AD-1346 M3e4c3b (D258): the directories it classifies.
_CLASSIFIED = (
    "src/probos/agents/",
    "src/probos/consultation/",
    "src/probos/execution/",
    "src/probos/knowledge/",
    "src/probos/naval/",
    "src/probos/routers/",
    "src/probos/task_sessions/",
    "src/probos/tools/",
    "src/probos/ward_room/",
)
```
REPLACE:
```
_RECORDS = "src/probos/knowledge/records_store.py"
_IDEAS = "src/probos/cognitive/ready_room/idea_store.py"
#: AD-1346 M3e4c3b (D258) and M3e4c3c (D263): the directories they classify.
_CLASSIFIED = (
    "src/probos/agents/",
    "src/probos/cognitive/",
    "src/probos/consultation/",
    "src/probos/execution/",
    "src/probos/knowledge/",
    "src/probos/naval/",
    "src/probos/routers/",
    "src/probos/task_sessions/",
    "src/probos/tools/",
    "src/probos/ward_room/",
)
```

**M1-06** (`tests/test_ad1346_admission_file_write_census.py`)

SEARCH:
```
    assert len(found) == 1, (path, qualified, len(found))
    return found[0]


def test_every_file_with_a_file_write_is_a_row_and_every_row_is_one() -> None:
    """WF1 (D253, D254, D259; kills EF-12, EJ-2): a file that gains its first file write fails here."""
    found = file_write_files()
    assert sorted(found - FILE_WRITE_FILES.keys()) == []
    assert sorted(FILE_WRITE_FILES.keys() - found) == []
    assert len(found) == 72, len(found)
    kinds = Counter(_kind(cover) for cover in FILE_WRITE_FILES.values())
    assert kinds == {"Pending M3e4d": 1, "System": 19, "Pending M3e4c3c": 50, "OutsideRuntime": 2}, kinds
```
REPLACE:
```
    assert len(found) == 1, (path, qualified, len(found))
    return found[0]


def _called(node: ast.Call) -> str:
    """The name of the function ``node`` calls, a name or an attribute, else the empty string."""
    func = node.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def test_every_file_with_a_file_write_is_a_row_and_every_row_is_one() -> None:
    """WF1 (D253, D254, D259, D264; kills EF-12, EL-2): a file that gains its first file write fails here."""
    found = file_write_files()
    assert sorted(found - FILE_WRITE_FILES.keys()) == []
    assert sorted(FILE_WRITE_FILES.keys() - found) == []
    assert len(found) == 72, len(found)
    kinds = Counter(_kind(cover) for cover in FILE_WRITE_FILES.values())
    assert kinds == {"Pending M3e4d": 1, "System": 38, "Pending M3e4c3d": 31, "OutsideRuntime": 2}, kinds
```

**M1-07** (`tests/test_ad1346_admission_file_write_census.py`)

SEARCH:
```
def test_the_agent_attributed_row_writes_and_records_its_author() -> None:
    """WF3 (D239, D255; kills EF-7, EF-8, EJ-3)."""
    pending = {path for path, cover in FILE_WRITE_FILES.items() if isinstance(cover, Pending) and cover.owner == "M3e4d"}
```
REPLACE:
```
def test_the_agent_attributed_row_writes_and_records_its_author() -> None:
    """WF3 (D239, D255; kills EF-7, EF-8, EJ-3, EL-4)."""
    pending = {path for path, cover in FILE_WRITE_FILES.items() if isinstance(cover, Pending) and cover.owner == "M3e4d"}
```

**M1-08** (`tests/test_ad1346_admission_file_write_census.py`)

SEARCH:
```
def test_the_directories_m3e4c3b_classifies() -> None:
    """WF6 (D258, D259, D260; kills EJ-1, EJ-4, EJ-5, EJ-6): every row under ``_CLASSIFIED`` but the Ship's Records'
    is ``System`` under ``SHIP`` with a reason, and no ``System`` row lies elsewhere."""
    inside = sorted(path for path in FILE_WRITE_FILES if path.startswith(_CLASSIFIED))
    system = sorted(path for path, cover in FILE_WRITE_FILES.items() if isinstance(cover, System))
    assert system == [path for path in inside if path != _RECORDS], system
    assert all(cover.principal == SHIP and cover.reason for cover in FILE_WRITE_FILES.values() if isinstance(cover, System))
```
REPLACE:
```
def test_the_classified_directories() -> None:
    """WF6 (D258, D259, D260, D264, D265; kills EJ-1, EJ-4, EJ-5, EL-1, EL-3, EL-5): every row under ``_CLASSIFIED``
    but the Ship's Records' is ``System`` under ``SHIP`` with a reason, and no ``System`` row lies elsewhere."""
    inside = sorted(path for path in FILE_WRITE_FILES if path.startswith(_CLASSIFIED))
    system = sorted(path for path, cover in FILE_WRITE_FILES.items() if isinstance(cover, System))
    assert system == [path for path in inside if path != _RECORDS], system
    assert all(cover.principal == SHIP and cover.reason for cover in FILE_WRITE_FILES.values() if isinstance(cover, System))


def test_no_src_call_sets_captured_by_or_builds_an_agent_version() -> None:
    """WF7 (D239, D264, D265; kills EL-6, EL-7, EL-8): outside ``cognitive/ready_room/idea_store.py`` no ``src`` call
    passes a ``captured_by`` keyword, and no ``src`` call's function is named ``AgentVersion``."""
    found = sorted(
        (rel, node.lineno)
        for rel, source in src_sources().items()
        for node in ast.walk(ast.parse(source, filename=rel))
        if isinstance(node, ast.Call)
        and (
            (rel != _IDEAS and any(keyword.arg == "captured_by" for keyword in node.keywords))
            or _called(node) == "AgentVersion"
        )
    )
    assert found == [], found
```

## 8. Tracking (M2's commit)

**Date rule.** If M2 is committed on a local date other than 2026-11-01, the Builder puts the committing machine's local date in place of `2026-11-01` in exactly two strings, both new:
- the paragraph head `**AD-1346 (2026-11-01), #1604 M3e4c3c -- ` in M2-01's REPLACE;
- the heading `### AD-1346 M3e4c3c -- the file-write rows under cognitive/ classified (2026-11-01, #1604)` in M2-02's REPLACE.

Make the substitution before committing. M2-01's SEARCH is AD-1356 S3 and S4's head as it stands on `693fef40`; if that paragraph carries another date, use it in the SEARCH. No other deviation is permitted.

Then regenerate the ledger with `python -P scripts/gen_ad_ledger.py` (write mode) and commit both files as the tool writes them.

**Where the entries land.** M2-01 puts the new paragraph between `# ProbOS Progress` and AD-1356 S3 and S4's paragraph (`PROGRESS.md:3` on `693fef40`). M2-02 puts the entry directly above `### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)` (`DECISIONS.md:1244` on `693fef40`), the heading after M3e4c3b's entry (`:1232`). Neither new head carries a status keyword of `scripts/gen_ad_ledger.py:126-132` in its first 120 characters (`:139`).

**M2-01** (`PROGRESS.md`)

SEARCH:
```
# ProbOS Progress

**AD-1356 S3 and S4 (2026-11-02), #1722 -- 
```
REPLACE:
```
# ProbOS Progress

**AD-1346 (2026-11-01), #1604 M3e4c3c -- the file-write rows under cognitive/ classified.** The 19 file-write rows under `cognitive/` are now the ship's, which makes 38 of the 72 rows the ship's. The test that holds the classified directories now covers `cognitive/`. A new test fails if a `src` call outside the idea store passes a `captured_by` keyword. The other 31 rows wait for M3e4c3d. No `src` file changes and nothing is checked. The contract is `prompts/ad-1346-m3e4c3c-file-write-classification.md`.

**AD-1356 S3 and S4 (2026-11-02), #1722 -- 
```

**M2-02** (`DECISIONS.md`)

SEARCH:
```
### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```
REPLACE:
```
### AD-1346 M3e4c3c -- the file-write rows under cognitive/ classified (2026-11-01, #1604)

AD-1346 M3e4c3c is the third part of M3e4c3. It classifies the 19 file-write rows under `cognitive/`, each as the ship's; nothing is checked, refused or charged, and no `src` file changes. The contract is `prompts/ad-1346-m3e4c3c-file-write-classification.md`.

- *D263 (the cut).* The 19 rows under `cognitive/` now; M3e4c3d takes the other 31, whose owner becomes M3e4c3d. Rejected: all 50 now; a smaller group now.
- *D264 (the classification).* The 19 files are `System` under the ship's principal, by D239. Rejected: the idea store and the agent versioning file pending for M3e4d (no `src` call outside the idea store passes `captured_by`, and none builds an `AgentVersion`); the evidence collector pending for M3e4d (its `author_id` names what it observes); the build and SWE-harness writes pending for M3e4d (no author id).
- *D265 (the guards).* `cognitive/` joins WF6's directories and WF6 is renamed `test_the_classified_directories`; WF7 is new. Rejected: a second directory guard beside WF6; the 38 paths pinned; WF7 keyed on calls named `capture` and `promote`.
- *Tests.* WF1's counts change; WF6 is renamed; WF7 is new.
- *Residual, accepted.* Register R134 and R135 of the contract.
- *Reversal.* Revert the M3e4c3c commits.

### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```

## 9. What this does NOT change

- Any `src` file; `config.py`, `config/system.yaml`.
- `tests/fixtures/ad1346_effect_census.py`, the store census and store-family census fixtures and their tests (not edited).
- The behaviour of `file_write_scan`, `file_write_points` and `file_write_files`; `FILE_AGENT_ATTRIBUTED_SCOPES`; WF2's, WF3's, WF4's and WF5's bodies; WF6's body; the 72 keys of `FILE_WRITE_FILES`; WF1's point counts.
- Not built here: the classification of the 31 rows (M3e4c3d, register R135), any check (M3e4d), the evidence slice (M3e5). Not built (the epic's list): enforcement, a store rekey to the sovereign id, domain SQL, storage registration.

## 10. Mutation rows (one campaign of record on the M1 tree, after an unmutated baseline passes)

`--tests`: every row runs against `tests/test_ad1346_admission_file_write_census.py`. No two rows share a line. Each Line is a stripped line that occurs once in its file on M1's tree (Builder: confirm with `grep -c -F`; a count other than 1 is a hard stop for the Architect). EL-6 and EL-7 mutate a `src` line for the run and restore it.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| EL-1 | M1 | `tests/fixtures/ad1346_file_write_census.py` | `"src/probos/cognitive/dreaming.py": System(SHIP, "DreamingEngine.dream_cycle renames each non-primary entry of a consolidated cluster into an _archived directory beside it: no text"),` | `"src/probos/cognitive/dreaming.py": _UNCLASSIFIED,` | `test_the_classified_directories` |
| EL-2 | M1 | `tests/fixtures/ad1346_file_write_census.py` | `_UNCLASSIFIED: Final = Pending("M3e4c3d", "not yet classified under D239 and D218 (register R130)")` | `_UNCLASSIFIED: Final = Pending("M3e4c3c", "not yet classified under D239 and D218 (register R130)")` | `test_every_file_with_a_file_write_is_a_row_and_every_row_is_one` |
| EL-3 | M1 | `tests/test_ad1346_admission_file_write_census.py` | `"src/probos/cognitive/",` | `"src/probos/cognitive_x/",` | `test_the_classified_directories` |
| EL-4 | M1 | `tests/fixtures/ad1346_file_write_census.py` | `"src/probos/cognitive/ready_room/idea_store.py": System(SHIP, "IdeaCaptureStore._save writes the title, body and captured_by of each idea; WF7: no src call outside the file passes captured_by (D239)"),` | `"src/probos/cognitive/ready_room/idea_store.py": _AGENT_ATTRIBUTED_FILE,` | `test_the_agent_attributed_row_writes_and_records_its_author` |
| EL-5 | M1 | `tests/fixtures/ad1346_file_write_census.py` | `"src/probos/cognitive/skill_forge.py": System(SHIP, "SkillForge._write_files writes the files a model call generated into a temporary staging directory, with no author id (D239); forge removes the directory"),` | `"src/probos/cognitive/skill_forge.py": System("system:operator", "SkillForge._write_files writes the files a model call generated into a temporary staging directory, with no author id (D239); forge removes the directory"),` | `test_the_classified_directories` |
| EL-6 | M1 | `src/probos/startup/finalize.py` | `runtime.idea_capture_store = IdeaCaptureStore(` | `runtime.idea_capture_store = IdeaCaptureStore(captured_by="x",` | `test_no_src_call_sets_captured_by_or_builds_an_agent_version` |
| EL-7 | M1 | `src/probos/startup/finalize.py` | `agent_persistence = LocalDiskPersistence(root_dir=cfg.persistence_root_dir)` | `agent_persistence = AgentVersion(root_dir=cfg.persistence_root_dir)` | `test_no_src_call_sets_captured_by_or_builds_an_agent_version` |
| EL-8 | M1 | `tests/test_ad1346_admission_file_write_census.py` | `(rel != _IDEAS and any(keyword.arg == "captured_by" for keyword in node.keywords))` | `(any(keyword.arg == "captured_by" for keyword in node.keywords))` | `test_no_src_call_sets_captured_by_or_builds_an_agent_version` |

The campaign also re-runs M3e4c3b's EJ-1, EJ-4 and EJ-5 (killed now by `test_the_classified_directories`), EJ-3 (by `test_the_agent_attributed_row_writes_and_records_its_author`) and EJ-7 (by `test_the_command_line_rows`), as M3e4c3b's §10 writes them; M1 leaves their lines unchanged.

**Expected to survive, among them:**
- a row's reason text changed to another non-empty text;
- the order of `_CLASSIFIED`'s members changed;
- WF7's `"AgentVersion"` or `"captured_by"` changed to another name.

## 11. Verified Against Codebase (2026-11-01, read on `caabbf5c`)

```
git log --oneline -5 -> caabbf5c (M3e4c3b M2), 655ac42c (M3e4c3b M1), fd541ef7 (M3e4c3b contract), ac82876a (M3e4c3a merge), be9f5294
git ls-files --eol tests/fixtures/ad1346_file_write_census.py tests/test_ad1346_admission_file_write_census.py PROGRESS.md DECISIONS.md -> i/lf w/crlf for each
Read tests/fixtures/ad1346_file_write_census.py :1-222 (_AGENT_ATTRIBUTED_FILE :135; _UNCLASSIFIED :136; FILE_WRITE_FILES :145-222; ward_room row :170; comment :171; cognitive rows :181-199; credential_store :200)
Read tests/test_ad1346_admission_file_write_census.py :1-247 (WF1 docstring :7-9; WF6 docstring :27-28, close :29; _RECORDS :45; _CLASSIFIED :46-57; _function end :138-139; WF1 :142-164, kinds :149; WF3 :199-216; WF4 :219-225; WF6 :241-247)
Grep tests/fixtures/ad1346_effect_census.py -> SHIP :52; OUTSIDE_RUNTIME :56; System :81; Pending :92; src_sources :248-251 (lru_cache)
logs/ad1346/evidence-points-m3e4c3c-rows.txt :32-69 -> the 38 points of the 19 cognitive/ files cited in D264 (file, line, scope, name)
Reads (src/probos/cognitive/): agent_patcher.py :200-244; builder.py :113-125, :1749-1773, :3246-3285, :3470-3510, :3675-3704; chain_checkpoint.py :1-130; checkpoint.py :1-110;
  copilot_adapter.py :360-387; dm/artifact_extractor.py :187-211, :684-749; dream_manifest.py :1-90; dreaming.py :995-1038; evidence_collector.py :137-271, :520-569;
  peer_observation_monitor.py :576-589; ready_room/idea_store.py :1-140; sandbox.py :60-147; scout.py :84-98, :206-293; self_improvement/versioning.py :1-80, :100-164;
  self_mod.py :590-614; session_manager.py :1-199; skill_catalog.py :645-845; skill_forge.py :1-60, :160-317; swe_harness/tools.py :205-243, :1015-1047, :1150-1171
Grep '^def |^async def |^class |^    def |^    async def ' src/probos/cognitive/builder.py
Grep 'captured_by\s*=' src -> idea_store.py :76 :125
Grep '\.capture\(|IdeaCaptureStore|idea_store' src; Grep 'idea_capture_store' src -> finalize.py :4900 :4903 :4907 :4921 and the package's own lines
Grep 'AgentVersion\b' src; Grep '\bpromote\(|_persistence\b' src; Grep 'AgentVersion\(|designer=|agent_persistence|persistence\.promote|\.promote\(record' src
Grep '\.record_observation\(' src -A 8 -> routers/thread_fanout.py:1447-1453 (author_id=thread_id); the others are working-memory and SPC objects
Read src/probos/startup/finalize.py :4898-4911
grep -c -F "runtime.idea_capture_store = IdeaCaptureStore(" src/probos/startup/finalize.py -> 1
grep -c -F "agent_persistence = LocalDiskPersistence(root_dir=cfg.persistence_root_dir)" src/probos/startup/finalize.py -> 1
Grep '^\| E[A-Z]-1 \| M1 \| `src/' prompts
Trackers and tools:
Read PROGRESS.md :1-4 (M3e4c3b's head :3)
Grep '^### (AD-1346 M3e4c3|Explicit delegation models)' DECISIONS.md -> :1219 :1232 :1243
Read DECISIONS.md :1232-1243; scripts/gen_ad_ledger.py :122-141
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> CEILING AD-1356
```

## Absence Verified (2026-11-01, run on `caabbf5c`)

```
CLAIM: D263 to D269, R134 to R139, WF7 and EL-<n> are unused
RUN:   rg -n '\bWF7\b|\bEL-[0-9]|\bD26[3-9]\b|\bR13[4-9]\b|M3e4c3d' . (rg's default ignore rules); the same pattern over logs/ad1346
FOUND: prompts/ad-1346-m3e4c2-store-family-census.md:776 and prompts/ad-1346-m3e4c3a-file-write-census.md :744 :746 :747 (CLAIM and FOUND lines naming R139 as unused); prompts/ad-1346-m3e4c3b-file-write-classification.md :62 (its owner-label option), :632 :634 :635 (CLAIM, FOUND and RE-RUN lines) and :716 (R133: "M3e4c3d: the 31 others"); logs/ad1346/answer-ad1346-m3e4c3.txt :789 :791; logs/ad1346/answer-ad1346-m3e4c3b.txt :37 :117 :689 :691 :763 (the same lines of the banked answer)
RE-RUN on the M3e4c3b merge `d5f10598` (Amendment 1), the first command only (the second reads the gitignored `logs/ad1346`): `prompts/ad-1346-m3e4c2-store-family-census.md:776`; `prompts/ad-1346-m3e4c3a-file-write-census.md` :744 :746 :747; `prompts/ad-1346-m3e4c3b-file-write-classification.md` :62, :632 :634 :635 and :718 (R133: "M3e4c3d: the 31 others", which M3e4c3b's amendment A2 moved from :716); no other file
RE-RUN on the AD-1356 S3 and S4 merge `693fef40` (Amendment 2), the first command only: the same lines of the same three files; no other file
HOLDS: yes

RUN:   rg -n 'test_the_directories_m3e4c3b_classifies|_CLASSIFIED\b|M3e4c3c|ad1346_file_write_census|FILE_WRITE_FILES' --glob '*.py' .
FOUND: tests/fixtures/ad1346_file_write_census.py :15 :136 :145 :171; tests/fixtures/ad1346_effect_census.py:66 (EFFECT_CLASSES text); tests/test_ad1346_admission_file_write_census.py :3 :4 :7 :8 :37 :39 :47 :145 :146 :148 :149 :201 :221 :224 :241 :242 :244 :245 :247
RE-RUN on the merge `d5f10598` (Amendment 1): the same lines of the same three files (the merge changes none of them); no other file
RE-RUN on the AD-1356 S3 and S4 merge `693fef40` (Amendment 2): the same lines of the same three files (`git diff --name-only d5f10598 693fef40` lists none of them); no other file

CLAIM: outside cognitive/ready_room/idea_store.py no src line passes captured_by as a keyword (WF7 passes on M1)
RUN:   rg -n 'captured_by\s*=' src
FOUND: src/probos/cognitive/ready_room/idea_store.py :76 :125
RE-RUN on `693fef40` (Amendment 2): the same two lines; no other file
HOLDS: yes

CLAIM: no src call builds an AgentVersion, and no src line reads an attribute named capture, or calls one named promote
RUN:   rg -n 'AgentVersion\b' src; rg -n '\.(capture|promote)\b' src; rg -n 'getattr\([^)]*["'"'"'](capture|promote|agent_persistence|idea_capture_store)["'"'"']' src
FOUND: AgentVersion: self_improvement/__init__.py :29 :39 (import, __all__); versioning.py :7 (docstring), :34 (class), :70 :86 :87 :99 :100 :129 :180 :183 :208 :214 (annotations); none a call. .capture/.promote: cognitive_agent.py:5406 (_on_demand.promote, read, not called), versioning.py:161 (a log string). getattr: nothing
RE-RUN on `693fef40` (Amendment 2): the same three commands print the same lines
HOLDS: yes

CLAIM: of the 19 cognitive/ files, only the ones named below hold an author-like name, and none of those names is in a write D264 classifies but evidence_collector.py's author_id and author_callsign, idea_store.py's captured_by and versioning.py's designer
RUN:   rg -c 'author|creator|created_by|requester|requested_by|designer|captured_by|posted_by' src/probos/cognitive (every file of the package, so all 19); then rg -n with the same pattern over builder.py, dm/artifact_extractor.py, dreaming.py, skill_forge.py, swe_harness/tools.py
FOUND: among the 19: builder.py 4 (:1688 :2907 :2984 :3628, comments "model-authored"); dm/artifact_extractor.py 3 (:552 docstring; :689 :743 created_by handed to artifact_store.add_version); dreaming.py 14 (:1013 :1146 :1373 write_entry authors; :2402-2461 a thread author read); evidence_collector.py 39; ready_room/idea_store.py 7; self_mod.py 15 (designer objects, :18-:667); self_improvement/versioning.py 2 (:40 :151); skill_forge.py 1 (:19 docstring); swe_harness/tools.py 2 (:197 :232 "authoriz"); the other ten: none
RE-RUN on `693fef40` (Amendment 2): `git diff --name-only d5f10598 693fef40 -- src/probos/cognitive/agent_patcher.py src/probos/cognitive/builder.py src/probos/cognitive/chain_checkpoint.py src/probos/cognitive/checkpoint.py src/probos/cognitive/copilot_adapter.py src/probos/cognitive/dm/artifact_extractor.py src/probos/cognitive/dream_manifest.py src/probos/cognitive/dreaming.py src/probos/cognitive/evidence_collector.py src/probos/cognitive/peer_observation_monitor.py src/probos/cognitive/ready_room/idea_store.py src/probos/cognitive/sandbox.py src/probos/cognitive/scout.py src/probos/cognitive/self_improvement/versioning.py src/probos/cognitive/self_mod.py src/probos/cognitive/session_manager.py src/probos/cognitive/skill_catalog.py src/probos/cognitive/skill_forge.py src/probos/cognitive/swe_harness/tools.py` prints nothing, so the counts and lines above stand
HOLDS: yes

CLAIM: Session, ChainCheckpoint, BuildSpec and ScoutFinding have no author field; write_checkpoint's dict has no author key; _rewrite_frontmatter sets no author key
RUN:   Read session_manager.py :32-43; chain_checkpoint.py :36-45; builder.py :113-124; scout.py :84-98; checkpoint.py :73-81; skill_catalog.py :799-810
FOUND: Session: id, platform, user_id, agent_type, started_at, last_activity, active_tasks, context. ChainCheckpoint: checkpoint_id, chain_name, suspended_at_step, suspended_at, running_context, reason. BuildSpec: title, description, target_files, reference_files, test_files, ad_number, branch_name, constraints. ScoutFinding: repo_full_name, stars, url, classification, relevance, credibility, reliability, summary, insight, language, license, topics. Checkpoint dict: checkpoint_id, dag_id, source_text, created_at, updated_at, node_states, dag_json
RE-RUN on `693fef40` (Amendment 2): `git diff --name-only d5f10598 693fef40 -- src/probos/cognitive/session_manager.py src/probos/cognitive/chain_checkpoint.py src/probos/cognitive/builder.py src/probos/cognitive/scout.py src/probos/cognitive/checkpoint.py src/probos/cognitive/skill_catalog.py` prints nothing, so the fields and keys above stand
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

- `git diff --stat <base>..HEAD -- src` prints nothing after M1 and after M2 (EL-6 and EL-7 are restored after the campaign).
- The collect-only count for `tests/test_ad1346_admission_file_write_census.py` is 7.
- For each §10 Line, `grep -c -F` prints 1. No Line contains `'`: `$pat = '<line>'; grep -c -F $pat <file>`.
- M1 is 8 SEARCH/REPLACE blocks (M1-01 and M1-02 in the fixture, M1-03 to M1-08 in the test); M2 is 2.
- `python -P scripts/gen_ad_ledger.py --check` exits 0 after M2.

## 13. Prior Art and Blind Spots

- **Internal.**
  - Adopted: D218 and D239 as M3e4c wrote them, including D239's classes "the agent id names the agent or subject the row is about" (the evidence collector) and "a copy of an agent's state" (the session's context).
  - Adopted: M3e4c3b's reason style ("written with no author id (D239)", "no text") and its `_CLASSIFIED` guard (D260), extended rather than duplicated.
  - Adopted: a mutation row that mutates a `src` line, as EX-1, EQ-1, EB-1, EG-1 and EH-1 do, to show WF7 fires.
- **External.** Skipped: the classification applies ProbOS's own D218 and D239 to its own files, with no outside analogue. `docs/research/reference-projects.md` was not read in this session; no row examined.
- **Blind spots, decided:** what this classification and WF7 do not see (register R134); the 31 rows left (register R135).

## 14. Diff Reviewer: properties to verify

1. No `src` file changes; only the fixture and the file-write test change in M1; `tests/fixtures/ad1346_effect_census.py` does not change.
2. `FILE_WRITE_FILES` keeps its 72 keys; its `System` rows are exactly the rows under `_CLASSIFIED` but `knowledge/records_store.py`; the other 31 are `_UNCLASSIFIED`, whose owner is `M3e4c3d`.
3. For each new `System` row, read the file's write points: the reason names what they record and asserts no caller, destination, count or ordering that the code or WF7 does not enforce. Each of the file's writes must also record no author id that a production caller sets to an agent's id or an HTTP request's value (D239).
4. WF1's counter, WF6's assertions and WF7's assertion agree with the table and with each docstring, in the code's branch order.
5. Each §10 mutant fails its named test on the M1 tree, and EL-6 and EL-7 leave `src` restored.
6. No sentence in a changed docstring, comment or reason asserts a property the code or a test does not establish.

## 15. Acceptance criteria

- The M1 and M2 focused gates pass as written in §4.
- The §12 checks hold.
- The §10 campaign of record kills EL-1 to EL-8 and the re-run EJ rows, each by its named test, after an unmutated baseline passes.
- The broad gate passes once after M2, with its receipt.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Corrections to this contract

**Amendment 1 (2026-11-02, the orchestrator, before the build, after M3e4c3b's merge as `d5f10598`).** Changed, against the contract as the Architect banked it:
- Anchors, and "Which text describes the head": M3e4c3b's merge and the two files it changes against the read commit.
- §5: the sentence on WF6's name says that the test file that defines it is the one Python file that names it.
- Absence Verified, the first entry: its CLAIM no longer says that M3e4c3d appears only as M3e4c3b's label for the next slice (M3e4c3b's own CLAIM line, `:632`, names it too); the entry carries a re-run on the merge.
- Absence Verified, the second entry: its CLAIM line and its HOLDS line are deleted. `tests/fixtures/ad1346_effect_census.py:66` names FILE_WRITE_FILES and the fixture's module in its `EFFECT_CLASSES` text, which the entry's own FOUND line lists; its RUN and FOUND lines stay, and it carries a re-run on the merge.
- Absence Verified, the fifth entry: its CLAIM names `author_callsign` beside `author_id` among the names that `evidence_collector.py` writes (`_render_yaml`, `:578-590`, writes both).
Unchanged: every SEARCH text and every REPLACE text of §7 and §8; every count and every row's type and key; and every record of §11 and entry of Absence Verified but those named above.

**Amendment 2 (2026-11-03, the orchestrator, before the review, after AD-1356 S3 and S4's merge as `693fef40`).** The candidate waited while other work merged and is re-based on `693fef40` (PR #1744; its tree `1580cfea56b2` is the gated tree). Changed, against Amendment 1's contract:
- Dependencies, Anchors and "Which text describes the head": the S3 and S4 merge and the two tracker anchors on it.
- §8: M2-01's SEARCH is AD-1356 S3 and S4's paragraph head (M3e4c3b's is no longer the first paragraph), and the last line of M2-01's REPLACE repeats it. M2-02's SEARCH is BF-946's heading, the heading after M3e4c3b's entry (the heading it named before is no longer the next one), and the last line of M2-02's REPLACE repeats it. The two sentences that name these anchors say so.
- Absence Verified: each entry carries a re-run on the merge.
Unchanged: every other SEARCH text and REPLACE text of §7 and §8; every count and every row's type and key; every §10 row; and every other record of §11 and entry of Absence Verified.

**Amendment 3 (2026-11-03, the orchestrator, after review round 1).** The review found seven statements that were not true of the candidate. Sweeping for the siblings of its fourth turned up three more places that name WF7 as what holds "no `src` call builds an `AgentVersion`": WF7 holds it only for a call whose function is named so (register R134 says so). Each is deleted or shortened; the fixture's two row reasons, `PROGRESS.md`'s paragraph and `DECISIONS.md`'s D264 line are repaired in the commit that records this amendment. Changed, against Amendment 2's contract:
- §3, the row of `cognitive/self_improvement/versioning.py`: "the first held by WF7" is deleted from its last cell.
- §5: the sentence on WF6's earlier test name (Amendment 1 had reworded it) is deleted.
- §7.1, M1-02: the reason of `cognitive/builder.py` no longer says "of each file change", and the reason of `cognitive/self_improvement/versioning.py` no longer says "WF7:" before its absence (their REPLACE, and the fixture's rows).
- §8, M2-01: the sentence on the new test no longer says that it fails if a `src` call builds an `AgentVersion` (its REPLACE, and `PROGRESS.md`'s paragraph). M2-02: D264's first parenthesis no longer ends with ": WF7" (its REPLACE, and `DECISIONS.md`).
- §11: the results after `->` of the `builder.py` definitions record and of the earlier-campaigns record are deleted.
- Absence Verified, the sixth entry: the last fragment of its FOUND line, the frontmatter keys, is deleted.
- §12: the bullet that gave the file inventory from the base to the head is deleted.
Unchanged: every SEARCH text; every other REPLACE text of §7 and §8; every count and every row's type and key; every §10 row.

## For the register (#1604)

- **R133:** advanced. The 19 rows under `cognitive/` are classified as the ship's (D264); the 31 left carry the owner M3e4c3d (D263) and are register R135's.
- **R113:** unchanged; this slice adds no file pending for M3e4d.
- **R134:** what this classification does not see:
  - a row is a file, and its reason holds for the code read on `caabbf5c`. An edit that adds an author field to `Session`, `ChainCheckpoint`, `BuildSpec`, `ScoutFinding` or `write_checkpoint`'s dict is seen by none of WF1 to WF7;
  - WF7 sees a call by its keyword or by its function's name. It does not see a `captured_by` passed through `**` unpacking, an `AgentVersion` built under another name or through `dataclasses.replace`, or another object passed to `LocalDiskPersistence.promote` as its version;
  - writes through `tempfile.NamedTemporaryFile` are not points (register R129). `agent_patcher.py:202`, `sandbox.py:79` and `self_mod.py:592` write source into the temporary files whose deletes are these rows' points;
  - `cognitive/dm/artifact_extractor.py` hands an artifact's bytes to `attachment_store.write` (`:723`) and `created_by` to `artifact_store.add_version` (`:737-744`); neither is a point of its file;
  - `cognitive/dreaming.py:1012-1017` calls `RecordsStore.write_entry` with the author that the primary entry's frontmatter holds; that write is the Ship's Records' row's (register R113, R131);
  - callers added after `caabbf5c` are not read, except where WF7 sees them.
- **R135:** the order for the 31 `Pending("M3e4c3d")` rows:
  1. M3e4c3d: the 31 files under `attachments/`, `audio/`, `avatars/`, `captain_card/`, `experience/desktop/`, `infrastructure/`, `integrations/`, `maintenance/`, `migration/`, `ontology/`, `perception/`, `security/`, `startup/` and `voice/`, and the top-level `credential_store.py`, `episodic_health.py`, `identity_key_store.py`, `pidfile_guard.py`, `proactive.py`, `provider_setup.py`, `runtime_config_service.py`, `shutdown_integrity.py` and `warm_boot.py`. Input from register R134: `FilesystemAttachmentStore.write` (`attachments/filesystem_store.py:333`) is a filesystem implementation of the `attachment_store.write` that `cognitive/dm/artifact_extractor.py:723` calls;
  2. M3e4d;
  3. M3e5.
