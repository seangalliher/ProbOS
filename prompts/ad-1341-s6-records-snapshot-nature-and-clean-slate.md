# AD-1341 S6: the `--full` Ship's Records snapshot, the nature description entry, and an opt-in `--clean-slate`

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-27

**Finished on the S5 repair candidate `4b3101f3` (S5 Amendment A3), 2026-10-27, by a second `claude-architect` run** (the first timed out after §7.18). Every SEARCH anchor in §7 that targets base text was re-verified on `4b3101f3` (§11). One defect was found and fixed in place: 7.10's `_pending_nature` called `archive.source_state` from `__main__.py`, which `tests/test_ad1341_s3_veto_store.py:517` forbids (only `knowledge/archive_promotion.py` names `source_state`). 7.8 now adds `review_nature_description`, and `_pending_nature` calls it. §8 to §15 and the register were written by this run.

**Status:** build-ready. This is slice 6 of 6 of #1569. No new AD or BF number (a slice of #1569). **Base:** `origin/main` `7cb0b212d7bd0b8b60eafc7c870d284afaf087ff` (the merge of S5, PR #1688, which has S1 to S5 and BF-939 below it); its tree `fcafef183846941f0838c32260cfcbd786f4bd44` equals S5's gate's. **Re-anchored by the orchestrator on the merge (2026-10-27):** this paragraph, 7.4's label line (it named `scripts/check_store_registry.py` as the file of a `store-baseline.yaml` pair, which the apply tool took literally; it now names both) and the line numbers of the S5 anchors table. The Architect drafted this contract on S5's repair candidate `4b3101f3` (S5 Amendment A3 in), finished it there and amended it once (A1, below) after the orchestrator's oracle census; S5 then took its Amendments A4 and A5. The orchestrator's oracle on S5's gated head applies all 50 pairs (M1 14, M2 11, M3 23, trackers 2) with no failure, so no anchor moved. Every SEARCH below anchors on S1 to S5 text or older, or on S6's own earlier milestone, except the S5 anchors listed in **S5 anchors this contract depends on** (after §11). **Captain:** nothing in this slice meets a Captain condition (D17). Overrulable, as recorded: D3 (the snapshot keeps every classification), D8 (`--skip-promotion` skips the snapshot too), D10 (skills are not described) and D12 (the clean slate leaves the skill catalog and AD-1287's profiles alone).

**Milestones and tiers:**
- **M1, the `--full` Ship's Records snapshot.** **HIGH**: it changes what a tier 3 reset keeps and when it refuses, adds two tables to the Ship's Archive's file, and adds the Captain's erasure of a snapshot.
- **M2, the nature description entry.** **HIGH**: a new archive source kind, written before every tier 2 and 3 reset, under the Captain's review and veto.
- **M3, `--clean-slate`.** **HIGH**: a new destructive option of `probos reset`, with its audit marker and recovery.
- **M4, trackers.**

Each milestone is one Builder delegation and one local commit, built in order. The broad gate is the orchestrator's single canonical run, once, after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1341-s6 --receipt logs/gates/ad1341-s6.receipt.json`. The Builder runs only the focused gates in §4. Each of M1, M2 and M3 gets a cross-family review (`gpt-6.1-sol`; D16). One mutation campaign runs on the assembled tree (§10).

**Tests:**
- New: `tests/test_ad1341_s6_records_snapshot.py` (M1), `tests/test_ad1341_s6_nature_description.py` (M2), `tests/test_ad1341_s6_clean_slate.py` (M3).
- Updated, with an inline reason: `tests/test_ad1341_s1_archive_store.py` (M2: the closed `SourceKind` set).
- **No test touches a real data directory.** Each new file has an autouse fixture that points `LOCALAPPDATA`, `APPDATA`, `USERPROFILE`, `HOME` and `XDG_DATA_HOME` under `tmp_path` and makes `probos.__main__._default_data_dir` raise. Every reset and every `--clean-slate` runs on a `tmp_path` data directory with a `tmp_path` archive. The Builder never runs `probos reset` or `--clean-slate` outside these tests, and never against `%LOCALAPPDATA%\ProbOS`.

**Amendment A1 (2026-10-27, `claude-architect`, census on the oracle `4fd61f91`):** 48 of 49 rows were killed. D-6 survived because N1's procedures were created in the same order as their completions. 7.12 now creates the anti-pattern first (p-3 at `_B + 30.0`) and asserts that premise, so `_EXPECTED` pins the listing's order. P-18 now names the ledger test alone: the CLI checks `erased_at` before it marks, so X12's rerun never reaches that guard. Only 7.12, §6, §10 and §14 change. No test is added, so §4's lists and the census baseline keep their counts.

**Amendment A2 (2026-10-27, `claude-architect`, round 1 of the cross-family review on `f9afeb59`, tree `61e4fce9`: reviewers A, B and C all NOT READY):** most findings share one shape: a guard placed after the first write, or a check of one path of a set. A2 adds one reset preflight (`_reset_preflight`, shared by the dry run) that refuses, before the confirmation, the pidfile and the promotion, every refusal it can know: the snapshot's plan, root, key and destination (M1) and, with `--clean-slate`, the shape of `procedures/` (M3). S1 A4's overlap also protects the snapshots directory at every tier (M1) and counts `procedures/` with `--clean-slate` (M3). The snapshot is published by a hard link that never replaces a name, reads its root with `lstat`, refuses a link in its destination and reads its tag files back; the erasure checks what it deletes before its marker (M1). The description is read before the snapshot and archived after it, once per generation; `pending` and the veto print its text; its read-only claim is narrowed (M2). The generation's close is recorded last, after any clean slate (M3). A-F8 is recorded (R29). Changed: §2, §3, §4, §5, §6, §7 (7.1, 7.5, 7.6, 7.8 to 7.10, 7.12, 7.17, 7.18), §8, §9, §10 (70 rows), §11, §12, §13, §14, §15 and the register (R14, R15, R28 to R40). Expected (analysis, before A3): the new files 43, 21 and 28 cases; the focused lists M1 692, M2 586 and M3 689 passed, 1 skipped each; the census baseline 138.

**Amendment A3 (2026-10-27, `claude-architect`, census on the A2 oracle `47568aa7`, tree `d3bd66a8`):** 69 of 70 rows were killed. P-8 (`if bag_zip.namelist() != expected:`) survived. A2's tag read-back (P-33's line) opens every tag file by name, so X3's `member-missing` case now refuses at that open (`KeyError`) even with the member-list check disabled. The one thing that check alone refuses is a member the bag does not list, and no test wrote one. 7.6 adds the fault `member-extra` (one more member after `bagit.txt`), so X3 has ten cases and P-8's killer is that case. `member-missing` stays: a missing tag file refuses, whichever check sees it. No production change: the check is correct; only its test data had stopped reaching it. Changed: §3 (D5's map), §4, §6 (X3), 7.6, §10 (the closing notes; the rows and their count are unchanged), the A3 verification, §14 (4) and the register (R41). The pair counts are unchanged. Expected (analysis): the new files 44, 21 and 28 cases; the focused lists M1 693, M2 587 and M3 690 passed, 1 skipped each; the census baseline 139.

**Amendment A4 (2026-10-27, `claude-architect`, round 2 of the cross-family review on `2a1b6319`, tree `94a75834`: reviewers A, B and C all NOT READY):** four findings, all fixed; none recorded instead (A-F8 stays R29). **A-R2-F1** (P1, ordinary on POSIX, regression): `is_link_status` evaluated `stat.IO_REPARSE_TAG_MOUNT_POINT`, which CPython defines on Windows builds only, so every full reset, its dry run, `--clean-slate` and a snapshot's erasure raised `AttributeError` on Linux and macOS; it now compares with the module's own constant `0xA0000003`, and the tests swap `records_snapshot`'s `stat` for a POSIX build's (X18, X19, C15). **A-R2-F2** (P2, injected, regression): a temporary name `publish` could not remove after its link kept the snapshot readable under a second name after its erasure; the erasure now removes that alias first, by file identity, and the listing says when an erasure has not finished (X17, X17b). **R2-B1 = C-R2-F1** (P2, ordinary): a refused `--clean-slate` dry run still sized `procedures/` and opened `procedures.db` through the link; a refused dry run now prints the refusal and nothing else (X14b, C14). **C-R2-F2** (P3, regression): the skip's message said "the reason is recorded" before the close; it now says it will be (C13). A POSIX audit of S6 (§11) found no other break. Changed: §3 (D5, D6, D7, D13, the tests table, effect 9), §4, §5, §6, §7 (7.1; 7.5 pairs 2, 6, 8 and 10; 7.6; 7.17 pairs 10 and 12e; 7.18), §8, §9, §10 (78 rows), §11, §12, §13, §14 (4, 5, 7, 17, 19), §15 and the register (R42 to R47). Pair counts unchanged. Expected (analysis): the new files 50, 21 and 31 cases; the focused lists M1 699, M2 593 and M3 699 passed, 1 skipped each; the census baseline 148. This delta is round 3.

**Amendment A5 (2026-10-27, `claude-architect`, round 3 on `77b65917`, tree `d7d00d4f`: reviewers B and C READY, A NOT READY; the round-three brake decided *continue*):** one finding, fixed. **A-R3-F1** (P2, injected only, regression): `retained_alias` took `os.path.samestat` as proof that the `.{name}.partial` sibling is the snapshot's own file, but `samestat` compares `st_dev` and `st_ino` only, and CPython documents `st_ino` as identifying a file only if nonzero. With both indices reported as 0, the erasure removed another file and exited 0. `retained_alias` now raises `SnapshotRefused` when both names exist and either index is 0. The erasure's preflight (`_snapshot_file_problem`) refuses on it before its marker: exit 1, both names and the row unchanged. A zero index with no temporary name beside the snapshot is unaffected, and so is R44 (X17c; P-44, P-45). Two corrections change no behaviour: the POSIX stand-ins' docstrings and the POSIX audit's row 17 claimed equality with a POSIX build's `stat`, but `Lib/stat.py` defines the 17 `FILE_ATTRIBUTE_*` constants on every platform, so the stand-ins are stricter (no S6 module reads either set). X18's source scan skips `knowledge/nature_description.py` while it is absent (M1's stage only), so M1's list passes on its own; the case count is unchanged. Changed: §3 (D7, the tests table, effect 10), §4, §5, §6, §7 (7.1; 7.5's `_erase_snapshot` and `_snapshot_file_problem`; 7.6; 7.18's stand-in docstring), §10 (80 rows), §11, §12, §13, §14 (5), §15 and the register (R48, R49). Pair counts unchanged. Expected (analysis): the new files 51, 21 and 31 cases; the focused lists M1 700, M2 594 and M3 700 passed, 1 skipped each; the census baseline 149. Round 4: reviewer A alone, on A5's delta.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| `RESET_TIERS`: tier 1 `scheduled_tasks.db`, `events.db`, `checkpoints/`; tier 2 the cognition and identity files, `semantic/`, the knowledge subdirectories and `ontology/instance_id`; tier 3 `ward_room.db` (copied to `archives/` first), `workforce.db`, `ship-records/`, `scout_reports/`. `archives/` is never cleared | present | `__main__.py:2642-2681` |
| A tier's directory is cleared by `dpath.glob("*")`: every entry, `.git` and dot-files included | present | `__main__.py:3062-3072` |
| `procedures/` (Cognitive JIT: `procedures.db`, the AD-1326 `procedures_challenges.db`, the `chroma/` semantic index) is in no tier, so it survives every reset | present | `runtime.py:3028-3031`; `procedure_store.py:207`, `:438-440`; `storage_declarations.py:229`; Absence S6-AV2 |
| Every executing reset holds the AD-816 pidfile; tier 2 and 3 promote first (S1) and refuse on any failure with nothing deleted; `--skip-promotion REASON` records a skipped generation; `--dry-run` shows the plan and opens no archive | present | `__main__.py:2987-3008`, `:3247-3320`, `:3323-3361` |
| A reset refuses when the archive lies inside what it deletes (S1 A4) | present | `__main__.py:2942-2951`, `:3216-3244` |
| The stand-down (S4) runs in the vessel before a reset; the reset neither waits for it nor needs it | present | S4 contract D2; not re-read |
| `RecordsStore.list_entries()` reads `*.md` only and skips a file it cannot read or parse (S1 register RA3-1; S4 R20, F-649); its constructor creates nothing | present | `records_store.py:214-222`, `:1015-1045` |
| The archive: schema v1, one write `promote_entry` (only `archive_promotion.py` names it), the Captain's `erase_entry` and `veto_source` with content-free markers; `ArchiveStore` has 15 methods, exactly the AD-1270 SRP trigger | present | `archive_store.py:83-104`, `:228-281`, `:432-762`; `tests/test_ad1341_s1_promotion.py:426-437`; `scripts/check_architecture_principles.py:187-188`, `:558-569` |
| The Oracle's archive tier reads every row with no reader filter, so the archive holds `ship` and `fleet` only (C1); the Oracle tool cuts each entry to 1,200 characters | present | `archive_store.py:85-87`; `tools/oracle_query_tool.py:71`, `:119-129` |
| Nature channels: procedures (above); catalog skills are `SKILL.md` files in the installation's `config/skills/` (four tracked), indexed into `{data_dir}/cognitive_skills.db`; per-agent grants in `skill_grants.db`; `skills.db` (AD-428 proficiency) is a tier 2 file; AD-1287 execution profiles (`profile_qualifications.db`) are not wired in production | present | `startup/communication.py:694-718`; `skill_catalog.py:647-686`; `git ls-files config/skills`; `storage_declarations.py:198-216` |
| A catalog skill's `origin` is not durable: every boot re-scans `config/skills` and re-registers each file as `internal` (`INSERT OR REPLACE`), so a forged (`generated`) or imported skill reads as `internal` after a restart | present | `skill_catalog.py:162`, `:283-296`, `:309-335`; `skill_forge.py:13` |
| Ship's Records also hold each procedure's YAML (`procedures/{id}.yaml`, `procedures/_archived/`), written by the store and never read back | present | `procedure_store.py:3`, `:705-729`, `:1731`; Absence S6-AV2 |
| The ship's DID is `did:probos:{instance_id}`; the instance id file is written once, at the first boot | present | `identity.py:103-111`; `ontology/loader.py:95-102` |
| AD-1265's backups copy `*.db` files only, from the data root and the archive's directory | present | `infrastructure/backup_inventory.py:216-247`, `:272` |
| The default connection factory opens SQLite read-only (`mode=ro`, never creates the file); that keyword is not part of the `ConnectionFactory` protocol | present | `storage/sqlite_factory.py:18-38`; `protocols.py:362-371` |
| Every reset fake outside the AD-1341 tests sets `archive.enabled = False`, so it never reaches the promotion | present | `tests/test_reset_integration.py:52-56`; `tests/test_distribution.py:1123-1124`; `tests/test_proactive.py:719`; `tests/test_identity_deterministic.py:140-141` |
| The live archive held 0 rows at schema v1 on 2026-10-26; the vessel is stopped (2026-10-25 22:31:43 local) | taken as given | #1569 comments; not read (Not verified) |

## 1. Problem

#1569 Decision 2: "At `--full` it also archives the Ship's Records snapshot, keyed by ship DID and generation dates. This is AD-524's unbuilt item (1)." AD-524 item (1): "snapshot the Ship's Records git repo into a persistent archive location (outside `data/`). Archive keyed by ship DID (AD-441) + generation dates. Contains all notebooks, duty logs, captain's logs, reports" (`docs/development/roadmap-era-5-completed.md:2523`). The Captain's amendment of 2026-10-16 replaces the "champion procedures" source with a **description entry** ("which procedures and skills a generation developed and why. The procedure itself stays in its store"), and asks for **a clean-slate option** ("a reset that also clears nature ... The default keeps nature").

Four things are missing:
1. **A `--full` reset deletes Ship's Records with nothing kept** but what S1 to S5 promote (`ship`/`fleet` sources that meet a criterion). Everything else (draft and private notebooks, duty logs, manuals, a withheld or vetoed note) is gone.
2. **RA3-1 (S1, owner S6) and F-649 (S4 R20):** a file the listing cannot decode, or cannot read at that moment, is neither promoted nor reported, and a tier 3 reset deletes it.
3. **No record of a generation's nature.** Procedures persist as nature with no culture-side account of what a crew developed.
4. **No clean slate.** Nature survives every tier.

## 2. Solution overview

- **M1, the snapshot.** At tier 3, after the promotion and before the generation's close, the reset copies every regular file of `{data_dir}/ship-records` (except the top-level `.git/` and `procedures/`) byte for byte into one ZIP file holding one BagIt bag (RFC 8493), at `{archive_dir}/ship-records-snapshots/{timeline_id}/{started}_{ended}.zip`. It is written under a temporary name, flushed, read back and checked, recorded in a new content-free table `archive_snapshots`, then published by one hard link that never replaces a name (A2). Any failure refuses the reset with nothing deleted, and every refusal that can be known beforehand comes before anything is written (A2's preflight). The reset names the Markdown files Ship's Records cannot list (RA3-1). `probos archive snapshots` lists them; `probos archive erase-snapshot ID --reason TEXT` marks the row first, then deletes the file. The rows live in a new class, `ArchiveLedger` (`knowledge/archive_ledger.py`), on its own connection, because `ArchiveStore` is at the SRP method trigger. `ArchiveStore._SCHEMA` creates the table.
- **M2, the nature description.** At tier 2 and 3, after the promotion, the reset archives one `SourceKind.NATURE_DESCRIPTION` entry per generation (`nature-description/{timeline_id}`, `ship`): the Cognitive JIT procedures created since the ship's first boot, with each one's name, description, evolution, state, use counts and change summary, read read-only from `procedures.db`, never its steps, bounded to fit one Oracle tool entry, with no model call. `probos archive pending`, `veto` and `--dry-run` show it, and the Captain can veto it.
- **M3, `--clean-slate`.** An opt-in flag for tier 2 or 3: after the promotion (which described nature) and before the tier loop, it records a content-free marker in `nature_clearances`, then deletes `{data_dir}/procedures/`. A failure refuses before the tier loop, and the same command finishes it. It needs the archive enabled. It never touches the skill catalog, the Captain's grants, the archive, the snapshots or `archives/`.
- **M4.** Trackers.

No config field, event type, API route or HXI view. `ArchiveStore` gains no method; the archive's `user_version` stays 1.

## 3. Decisions

- **D1 (premises).** §0. S1's decisions (key, markers, C1, pidfile, store lock, fail-closed reset), S2's label, S3's review, veto and citation check, S4's notes and S5's continuous promotion all stand. Continuous promotion never archives the description or a snapshot: it runs `plan_promotion` over Ship's Records only.
- **D2 (the snapshot's shape and place).** Ranked:
  - **(A) chosen: one ZIP file beside the archive, holding one BagIt bag**, recorded by a content-free row. A file is the Captain's copy and is read by no agent; the bag's `manifest-sha256.txt` and `Payload-Oxum` make it checkable by any BagIt tool; one file publishes atomically and erases as one unit.
  - (B) an archive entry kind holding the records: rejected. The Oracle's archive tier gives every row to every later crew (§0), so draft, department and private notebooks would reach them (C1, the Captain's open privacy question), and multi-megabyte rows would enter the Oracle's LIKE search.
  - (C) one archive entry per document: rejected for the same reason, and it duplicates S1's promotion.
  - (D) a `git bundle` of the records repository: rejected. It needs git, and it holds only committed state, so it misses a note a write left uncommitted (S4 F-652) and the working tree the promotion read.
  - (E) a copied directory: rejected. Not atomic, and no single digest to record or erase.
- **D3 (what a snapshot holds).** Every regular file under `{data_dir}/ship-records`, the directory `RESET_TIERS[3]` deletes, so S6 keeps exactly what `--full` deletes. Every classification, private included: no ProbOS reader is built (Absence S6-AV4), so no agent gains a read path; the file is readable only by the account that already reads `data_dir`. **Reframing (for the record):** `private` protects a note from other agents, and the snapshot gives no agent access, so keeping the copy weakens no access control. Any later reader (AD-524 items 2 and 3) must apply the classification rule (register R5). **The Captain may overrule this** and keep only `ship` and `fleet`. Left out: the top-level `.git/` (history; the working tree is what the promotion read, register R4) and `procedures/` (procedure bodies stay in their store as nature: the amendment's "the procedure itself stays in its store"; with `--clean-slate` they are cleared deliberately). A custom `records.repo_path` outside the data directory is not deleted by `--full` and so not snapshotted (register R3).
- **D4 (the key and the name).** `{timeline_id}/{started}_{ended}.zip` under `ship-records-snapshots/` beside the archive's database (`resolve_archive_db_path(config.archive).parent`). `timeline_id` is the instance id and must match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` (a UUID does); the ship DID (`did:probos:{timeline_id}`, `generate_ship_did`) goes in `bag-info.txt` (`External-Identifier`) and the row, because a DID's colons cannot name a Windows directory. `started` is the modification time of `ontology/instance_id` (the first boot, register R9); `ended` is the snapshot's time; both UTC. The snapshots directory cannot lie inside what a reset deletes: **A2 (A-F2)** resolves it (links, junctions, `..`, the platform's case rule) and S1 A4's overlap refuses, at every tier, a reset whose targets hold it, equal it or lie inside it; a link or junction at it or at the timeline's directory refuses a tier 3 reset in the preflight and again in `prepare_snapshot`. To keep snapshots elsewhere, move `archive.db_path`.
- **D5 (bounds and refusals).** `SNAPSHOT_MAX_FILES = 100_000`, `SNAPSHOT_MAX_BYTES = 2 GiB` (uncompressed), module constants (register R8). Beyond either, the snapshot refuses. It also refuses, naming the path: a link or junction anywhere inside (never followed: it may lead out of Ship's Records; `is_symlink() or is_junction()`, the precedent `profile_components.py:47`), a special file, a file that cannot be read now, a file whose size changes between the listing and the copy, an instance id that cannot name a directory, and an existing snapshot of the same name. The walk is an explicit `os.scandir` whose every `OSError` propagates (S4 A5's lesson: `os.walk` swallows them). **A2 (A-F1):** the root itself is read with one `lstat` (`records_snapshot.lstat_or_none`): only a root that is not there is an empty plan; any other error propagates, and a root that is a link or junction refuses. The reset's preflight runs the plan before anything is written. **A4 (A-R2-F1):** `is_link_status` compares `st_reparse_tag` (read with a default) with the module's own `_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003` (MS-FSCC 2.1.2.1), never with the `stat` module's name for it, which only Windows builds define; a POSIX status is judged by its mode alone, and any other reparse tag (a cloud placeholder) is not a link (R33 stands).
- **D6 (order, failure and interruption).** **A2:** first the preflight (`_reset_preflight`, before the confirmation, the pidfile and the promotion, so a reset it refuses has written nothing). Then, inside S1's `_promote_into_archive`: promote Ship's Records → (M2) read the nature description → (M1, tier 3) the snapshot: plan, write under `.{name}.partial`, flush and `fsync`, read back (member list, every payload SHA-256, every member's CRC, the tag files included), compute the file's SHA-256, **record the row, then publish** (`os.link`, which never replaces a name; then the temporary name is removed; a file system without hard links refuses) → (M2) archive the description (B-F2: after the snapshot, so a snapshot that fails leaves none) → (M3) the clean slate, if asked → the generation's close (`_close_generation`, C-F3) → the tier loop. Any failure removes the temporary file and refuses the reset with nothing deleted. So a generation is closed only once its snapshot is in place. Interrupted (Ctrl+C, a crash): the tier loop has not run; the next run promotes again (idempotent: present), takes a new snapshot under a new name and closes the generation. A publish that fails, or a crash between the row and the link, leaves the row, never deleted, whose file is missing (`archive snapshots` shows `missing`; register R15; X3b, A-F7). A failure after publishing (the generation row) leaves a complete snapshot, and the rerun adds a second (register R14). **A4 (R2-B1, C-R2-F1):** a dry run whose preflight refuses prints the refusal and nothing else, exit 0: no tier table (which sized the refused directory), no promotion plan and no description (which opened `procedures.db` through a refused link). The rule covers every preflight refusal: a reset that refuses does nothing, so a display of what it would clear or promote is false, and more than one refusal names a path that display would read through.
- **D7 (the ledger and the Captain's erasure).** `archive_snapshots` (timeline, ship DID, both dates, the relative path, the file's SHA-256, file count, bytes, recorded time, erased time and reason; unique on the path) is created by `ArchiveStore._SCHEMA`. Its writes are in `ArchiveLedger`, on a connection of its own, opened only once `ArchiveStore.initialize` has brought the file to version 1. Ranked: (a) chosen, a separate class; (b) three more `ArchiveStore` methods: rejected, `ArchiveStore` has 15 methods, the AD-1270 trigger (`SRP_MAX_DIRECT_METHODS = 15`, `>` fires), so one more is a new architecture violation; (c) a ledger sharing the store's connection through its private attributes: rejected (reach-through). `probos archive erase-snapshot ID --reason TEXT [--yes]` marks the row (reason and time) **before** it deletes the file, so no snapshot is removed unrecorded. A deletion that fails is reported (exit 1) and the same command finishes it. A row whose path is not a snapshot name is never opened. **A2 (A-F3):** before its marker, the erasure refuses (exit 1, nothing marked or deleted) a snapshots directory or a timeline directory that is a link or junction, and anything but a regular file at the snapshot's name (`_snapshot_file_problem`); nothing there is fine, so a `missing` row can still be marked. A row is never deleted; a second erasure keeps the first reason. The unlink does not overwrite the bytes (register R6). **A4 (A-R2-F2):** `publish` links the final name, then removes the temporary one; a removal denied after the link (a sharing violation on Windows) leaves the snapshot's own file under a second name, `.{name}.partial`. The erasure removes that alias first, when `lstat` shows it is the same file as the final name (`records_snapshot.retained_alias`, `os.path.samestat`: never another attempt's file or a copy), then the final name; while either remains it exits 1 and `probos archive snapshots` shows `(erased by the Captain; its file remains: ...)`, and the same command finishes it. Ranked: (i) chosen; (ii) retries in `publish`: rejected, a denial can outlast any bound, so (i) is needed anyway; (iii) a publish that refuses when the removal fails: rejected, the snapshot is already published and recorded, so refusing leaves the same alias and a refused reset; (iv) `os.rename` on Windows: rejected, two code paths (A2), and POSIX's link then unlink still needs (i). A temporary file with no final name is R44. **A5 (A-R3-F1):** `os.path.samestat` compares `st_dev` and `st_ino`, and an index of 0 identifies no file (CPython: "if non-zero, uniquely identifies the file"). So when both names exist and either reports 0, `retained_alias` raises `SnapshotRefused` and `_snapshot_file_problem` returns its message. The erasure refuses before its marker (exit 1, both names and the row unchanged), and the Captain removes the temporary name by hand after checking it. Ranked: (i) chosen, refuse before the marker; (ii) refuse after the marker: rejected, a rerun cannot finish it, so the row would record an erasure the command cannot complete; (iii) erase the final name and leave the temporary one: rejected, it announces completion while a possible second name of the snapshot stays readable, the defect A4 fixed; (iv) decide by the row's SHA-256: rejected, a digest proves equal bytes, not one file, and X17b keeps a copy with equal bytes. A zero index with no temporary name beside the snapshot erases as before. **What the Captain's review does to it:** a veto keeps a source out of canon; the snapshot keeps the Captain's copy of what the reset deletes, a vetoed or erased source's document included, as Ship's Records kept it before. **AD-754 (`/forget`):** a snapshot holds no episode, and the episodes its notes cite by id are wiped by the same reset; nothing changes for the erasure manager.
- **D8 (the skip, a missing instance id, a disabled archive).** `--skip-promotion REASON` at tier 3 skips the snapshot too, and says so; the recorded reason covers both. Ranked: (a) chosen, one audited escape; (b) a separate `--skip-snapshot REASON`: rejected, a second escape for one decision ("carry nothing forward"); a Captain who wants promotion without the snapshot runs a tier 2 reset first. **The Captain may overrule (a).** With no instance id, a tier 3 reset whose Ship's Records hold any file refuses (no ship to key a snapshot by), unless `--skip-promotion`; tier 2 is unchanged (S1 RA1-2). **A2 (A-F5):** that refusal is in the preflight, before anything is written, and the dry run shows it instead of promising a snapshot. With the archive disabled, nothing is promoted or snapshotted, as S1 D13 decided for promotion.
- **D9 (RA3-1 and F-649).** **RA3-1 closes:** a file Ship's Records cannot list is copied byte for byte into the snapshot before tier 3 deletes it, and the reset names every Markdown file the listing passed over (at most ten, then a count). It is still never promoted (register R17). **F-649 closes at tier 3:** a file that cannot be read at the reset's moment refuses the snapshot, and the reset. Tier 2 deletes no record, so nothing changes there.
- **D10 (the nature description: content, source, bounds).** One `ship`-classified `SourceKind.NATURE_DESCRIPTION` entry per generation, `source_ref = nature-description/{timeline_id}`, title "Procedures developed by the crew of timeline {timeline_id}", no author, no source episodes, written by `archive_promotion.promote_nature_description` (S1's census holds). **Content:** the count developed and the count active at the close; one line per procedure created at or after the ship's first boot, by completions: name, description, evolution type, state (active, retired, an anti-pattern), "c of s uses completed, f fell back", and an evolved one's change summary; "And N more in the procedure store." for the rest. **Never** `content_snapshot` (the steps) or any other column. **Source:** `{data_dir}/procedures/procedures.db`, opened read-only (`mode=ro`: the database's own bytes never change; for the vessel's WAL-mode store, `procedure_store.py:211`, SQLite may create or touch the `-wal` and `-shm` files beside it, `storage/sqlite_factory.py:28-31`; A2, B-F4, register R34), only columns every version of `procedure_records` has (`procedure_store.py:97-124`). **No model call.** Each text is folded to one line with control and format characters removed and cut (name 60, text 120). **Bound:** the content is at most 900 characters, so the whole entry with its title, S2's longest label and the tool's marker fits one Oracle tool entry (1,200), as S4 did for notes (N2 proves it through the real tool). At most 10 procedures are read for listing. **Skills are not described** (ranked: (a) chosen, a fixed statement in the module docstring and DECISIONS: the catalog is part of the installation and no durable fact says which crew forged a skill, §0; (b) list every catalog skill: rejected, it would attribute the shipped skills to the crew; (c) list `origin = generated` rows: rejected, the origin is overwritten at every boot). **The Captain may overrule (a)** once the origin is durable (register R10). The lineage stays in the store (amendment item 2): the description names no agent.
- **D11 (the description's governance).** Built by one function (`_nature_record` in `__main__.py`) for the reset, `--dry-run`, `probos archive pending` and `probos archive veto`. `pending` lists `nature-description/{timeline}` with what promoting it would do; `veto` accepts that reference; `--dry-run` prints the whole text. The veto is keyed by kind and reference (S3), so it holds whatever the content is at the reset. The Captain's `probos archive erase ENTRY_ID` removes an archived one, and its marker keeps it out at the next reset. **One per generation (A2, B-F2):** once an entry is archived for `nature-description/{timeline}`, with any content, a later description of that generation is `present`, never a revision (`_nature_state` in `archive_promotion.py`, which `pending` reads too); the reset archives it after the snapshot, so only a clean slate or a close that fails can come between the two (register R30). `pending` and the veto's confirmation print its title and whole text (A2, B-F1).
- **D12 (`--clean-slate`: semantics).** Name: `--clean-slate`, the amendment's own words. Tier 2 or 3 only (with `--soft` it exits 2: tier 1 keeps the crew). **Deletes:** `{data_dir}/procedures/` whole (`procedures.db`, the AD-1326 challenger ledger, the procedures' semantic index). **Never touches:** the skill catalog (`config/skills/`, part of the installation and its git checkout), `cognitive_skills.db` (its index, rebuilt from those files at boot), `skill_grants.db` (the Captain's grants), `profile_qualifications.db` (AD-1287, not wired, insert-only; register R12), the Ship's Archive and its snapshots, `archives/`, the Captain's config, and Ship's Records at tier 2 (its procedure YAML copies are never read back: Absence S6-AV2, register R11). Ranked: (a) chosen, a flag on tiers 2 and 3; (b) a tier 4: rejected, it would force Ship's Records' deletion to clear nature; (c) also delete generated skills under `config/skills`: rejected, files in the installation's checkout, and the origin is not durable. **The Captain may overrule (c).** A link or junction at `procedures`, or a file there, is refused by the preflight before anything is read through it, archived, recorded or closed, and again where it deletes (A2, B-F3, C-F2); so is a name there that cannot be inspected. With the flag, `procedures/` joins the targets S1 A4 protects the archive and its snapshots from (A2, C-F1), dry run included; `RESET_TIERS` is unchanged.
- **D13 (`--clean-slate`: confirmation, marker, recovery).** The confirmation panel and `--dry-run` name what it clears ("Nature (--clean-slate)"); `--yes` skips the prompt, as every reset. It needs the archive enabled (exit 2 otherwise): the marker is never skipped. **Order:** after the promotion (whose description records the nature being cleared) and before the tier loop: the marker (`nature_clearances`: timeline, tier, the cleared names, the procedure count, or -1 if the store could not be counted, and the time) **then** the deletion, **then** the generation's close (A2, C-F3: `_promote_into_archive` returns the close and `_close_generation` records it, so a failed deletion leaves no closed generation; without the flag the close follows the promotion as before). A failed marker deletes nothing; a failed deletion refuses before the tier loop (every crew file untouched) and the same command finishes it, recording a second marker (C4). **A4 (C-R2-F2):** the skip's message is printed before the clearance and the close, so it says the reason *will be recorded with the generation's close*; `_close_generation` reports its own failure, and the reset then refuses before its tier loop.
- **D14 (the Captain-facing statement, per tier).**

| Tier | Deletes | Kept first in the Ship's Archive | Keeps |
|---|---|---|---|
| 1 `--soft` | `scheduled_tasks.db`, `events.db`, `checkpoints/` (unchanged) | nothing | everything else, `procedures/` included |
| 2 (default) | tier 1, and the cognition and identity files, `semantic/`, the knowledge subdirectories, the instance id (unchanged) | S1-S5's promotion, **and S6's nature description** | Ship's Records, `procedures/` (nature), `archives/`, the archive and its snapshots, `config/skills` |
| 3 `--full` | tier 2, and `ward_room.db` (copied to `archives/` first), `workforce.db`, `ship-records/`, `scout_reports/` (unchanged) | as tier 2, **and the Ship's Records snapshot** (every file but `.git/` and `procedures/`) | `procedures/`, `archives/`, the archive and its snapshots, `config/skills` |
| `--clean-slate` (with 2 or 3) | also `procedures/` | also the clean slate's marker, before the deletion | `config/skills`, `skill_grants.db`, `cognitive_skills.db`, the archive and its snapshots, `archives/` |

  The statement (DECISIONS and PROGRESS carry it): "A `--full` reset now keeps every Ship's Records file it deletes, except the git history and the procedures' YAML copies, as one checked snapshot beside the Ship's Archive, read by no agent; it refuses, deleting nothing, when it cannot. Every tier 2 and 3 reset archives a description of the procedures the crew developed, never the procedures. `--clean-slate` also deletes the procedure store, after recording it; nothing else."
- **D15 (the earlier slices' rows: taken, left, still open).**

| Row | What | S6 | Reason |
|---|---|---|---|
| S1 RA3-1 (owner S6) | an undecodable records file deleted unpromoted at tier 3 | **taken** (D9) | the snapshot keeps it and the reset names it |
| F-649 (S4 R20) | an unreadable note deleted at tier 3 | **taken** for tier 3 (D9) | the snapshot refuses |
| S3 D2 B, S4 D? (C) | opt-in approval would lose pending sources at `--full` "because S6's snapshot is not built" | **reason removed**: a pending source is now snapshotted, though not promoted | the decision itself stays S3's and S4's |
| S5 R1 ("Owner: S6 or a follow-up") | automatic after-action triggers | **left** to a follow-up (register R1) | not one of S6's three items; it adds unattended model turns |
| F-661 (S4 R32) | `_stored_text` and alias graphs | done by S5 (D17) | |
| F-643, F-657 (writers outside ProbOS) | | **stay**; the snapshot copies what such a writer left (R13) | unchanged in kind |
| S1 C1 (the Captain's open question) | department and private notebooks in the archive | **untouched**: the snapshot is not an entry (D2 B) | |
| S1-S5 "S6" mentions | the snapshot, the description, the clean slate | taken (M1-M3) | |

- **D16 (tiers and review).** M1, M2 and M3 are HIGH (data integrity, what a reset keeps, a new archive source, a destructive option), each with a cross-family review and the mutation campaign (#1569's slicing: "a cross-family review and a mutation table for S1, S3 and S6").
- **D17 (the Captain).** Nothing meets a "Still requires the Captain" condition:
  - **No operation against a live system, and nothing destructive against a real data directory:** the build and every test run on `tmp_path` with the platform paths redirected; `--clean-slate` is never run outside its tests.
  - **No privacy, audit or approval control is weakened.** The snapshot creates no reader and no entry (D3); the description is `ship`, under the Captain's veto and erasure; the clean slate is the Captain's own amendment item 5, opt-in, confirmed and marked before it deletes; every new destructive path (the clean slate, a snapshot's erasure) records first. A `--full` reset refuses in new cases (it fails closed).
  - **No public API or schema break.** Two additive tables (`CREATE TABLE IF NOT EXISTS`, `user_version` stays 1), a `SourceKind` value in a TEXT column, new CLI flags and subcommands; no route or wire change.
  - **No new external spending.** No model call anywhere in S6.
- **D18 (not built).** A reader or HXI view of snapshots (AD-524 items 2 and 3), a `--verify` of a snapshot's digest, restore from a snapshot, a snapshot of `scout_reports/` and `workforce.db` (R2), automatic after-action triggers (R1), a durable skill origin (R10), fleet sharing.

**How each decision is tested:**

| Decision | Tests |
|---|---|
| D2, D3, D4 | X1 (the real reset; byte-for-byte payload, manifest, bag-info, row; no later crew reads it), X6, X8, X10 |
| D5 | X3 (ten faults through the real reset; A3: a member the bag does not list), X6 (both bounds, exactly at and one beyond), X7 (a link is never followed), X9 |
| D6 | X1, X3 (nothing deleted, no temporary file, no generation row), X3 `not-recorded` (the row fails after the file was written) |
| D7 | X11 (the ledger's row, unique path, the marker once, version check), X12 (list; erase; decline; a failed unlink then the rerun), X12b (a tampered row, a disabled archive, bad arguments), X13 (census) |
| D8 | X4, X5, X2 |
| D9 | X1 (the undecodable file kept and named), X3 `unreadable` |
| D10 | N1 (exact content through the real reset, the store unchanged, no steps, the label), N2 (the bound through the real Oracle tool), N3, N4, N6, N7 |
| D11 | N5 (pending, then the store changes, then veto, then the reset), N8 (dry run) |
| D12 | C1 (both tiers: what is deleted, and everything else byte-identical), C2 (nature kept at every tier without the flag), C3, C7 |
| D13 | C1 (the marker), C4 (recovery), C5 (a failed marker deletes nothing), C6 (confirmation and dry run), C10 |
| A2 | X3, X3b, X7b, X7c, X8b, X9, X9b, X12d, X14b, X16 (M1); N5, N9, N9b, N10, N11 (M2); C4, C7, C11, C12, C13 (M3) |
| A4 | X14b, X17, X17b, X18, X19 (M1); C13, C14, C15 (M3) |
| A5 | X17c (M1) |

Each decision that says "one X for two reads" has a case that changes X between them:
- **D6: one plan for the listing and the copy.** X3 `grew` and `shrank` change a file after `plan_snapshot` returned and before it is copied; the snapshot refuses.
- **D7: one row for the listing and the erasure.** X12 makes the file's deletion fail after the row is marked, then reruns: the listing and the rerun read the same row (erased, the first reason).
- **D11: one builder for `pending`, `veto` and the reset.** N5 adds a procedure between `pending` and the reset, so the reset's description differs from the reviewed one; the veto (by kind and reference) still keeps it out.
- **D13: the marker before the deletion.** C4 fails the deletion after the marker; C5 fails the marker before the deletion.

**Disclosed effects and bounds, each pinned:**
1. A tier 3 reset writes one snapshot (X1), refuses when it cannot (X3, X5), and prints what it kept and the files the listing passed over (X1). Bounds 100,000 files and 2 GiB (X6).
2. `archive_snapshots` and `nature_clearances` in the archive's file; `user_version` 1 (X11, C1).
3. `probos archive snapshots` and `probos archive erase-snapshot` (X12).
4. `SourceKind` gains `nature_description` (7.11). Every tier 2 and 3 reset archives at most one description per generation; a retried reset keeps the first (N1, N7, N9, N9b); at most 900 characters (N2).
5. `pending`, `veto` and `--dry-run` show the description (N5, N8).
6. `--clean-slate`, its marker and its refusals (C1-C7). The reset's summary says whether nature was kept or cleared (C1, C2).
7. A snapshot copies up to 2 GiB synchronously and reads it back once (register R16).
8. A2: new refusals, each before anything is written: a root or snapshot destination that is a link or junction or cannot be inspected (X7b, X7c, X16); an archive or snapshots directory inside or around what the reset deletes, `procedures/` included with `--clean-slate` (X16, C12); a link, junction or file at `procedures` (C7). At publish: a file system without hard links (X9b). The dry run says when the reset would refuse (X14b). The generation's close is recorded last (C4, C13).
9. A4: a refused dry run prints only its refusal (X14b, C14); an erasure also removes a temporary name the publish could not remove after its link, and the listing says when an erasure has not finished (X17, X17b); the link rule names nothing a POSIX build lacks (X18, X19, C15).
10. A5: an erasure removes a temporary name only when both names report a usable (nonzero) file index and they are one file; when either index is 0 it refuses before its marker and keeps both names (X17c).

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write each milestone's new test file first and run it on the milestone's base: it must fail at import (§6 names the error). If a test outside §7 fails, stop and report it; never delete or loosen a test. The broad gate is the orchestrator's single canonical run after M4.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** the snapshot | HIGH | 7.1 new `src/probos/knowledge/records_snapshot.py`; 7.2 new `src/probos/knowledge/archive_ledger.py`; 7.3 `src/probos/knowledge/archive_store.py`; 7.4 `docs/development/store-baseline.yaml`; 7.5 `src/probos/__main__.py`; 7.6 new `tests/test_ad1341_s6_records_snapshot.py` | `tests/test_ad1341_s6_records_snapshot.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s2_inherited_label.py tests/test_ad1341_s3_veto_store.py tests/test_ad1341_s3_review_cli.py tests/test_ad524_ships_archive.py tests/test_reset_integration.py tests/test_bf902_fts_reconciliation.py tests/test_ad1340_s1_restore_reset.py tests/test_distribution.py tests/test_identity_deterministic.py tests/test_ad1256_store_registry.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_store_registry.py --check` and `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` |
| **M2** the description | HIGH | 7.7 `src/probos/knowledge/archive_store.py`; 7.8 `src/probos/knowledge/archive_promotion.py`; 7.9 new `src/probos/knowledge/nature_description.py`; 7.10 `src/probos/__main__.py`; 7.11 `tests/test_ad1341_s1_archive_store.py`; 7.12 new `tests/test_ad1341_s6_nature_description.py` | `tests/test_ad1341_s6_nature_description.py tests/test_ad1341_s6_records_snapshot.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s2_inherited_label.py tests/test_ad1341_s3_review_cli.py tests/test_ad1341_s3_veto_store.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad1341_s5_after_action_format.py tests/test_ad1341_s5_continuous_promotion.py tests/test_procedure_store.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`; then `check_architecture_principles.py --check` |
| **M3** the clean slate | HIGH | 7.13 `src/probos/knowledge/archive_store.py`; 7.14 `docs/development/store-baseline.yaml`; 7.15 `src/probos/knowledge/archive_ledger.py`; 7.16 `src/probos/knowledge/nature_description.py`; 7.17 `src/probos/__main__.py`; 7.18 new `tests/test_ad1341_s6_clean_slate.py` | `tests/test_ad1341_s6_clean_slate.py tests/test_ad1341_s6_nature_description.py tests/test_ad1341_s6_records_snapshot.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s3_review_cli.py tests/test_reset_integration.py tests/test_bf902_fts_reconciliation.py tests/test_ad1340_s1_restore_reset.py tests/test_distribution.py tests/test_proactive.py tests/test_identity_deterministic.py tests/test_ad1256_store_registry.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`; then `check_store_registry.py --check` and `check_architecture_principles.py --check` |
| **M4** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

The oracle slices the milestones by heading: M1 is `### 7.1 ` to `### 7.7 `, M2 `### 7.7 ` to `### 7.13 `, M3 `### 7.13 ` to `## 8.`. Each subsection holds one milestone's pairs only. No measured counts yet: the orchestrator measures each list on its oracle. **A2 expected (analysis), with A3's one case:** M1's list 693 passed and 1 skipped (684 + 8 + 1), M2's 587 and 1 (574 + 8 + 4 + 1), M3's 690 and 1 (670 + 8 + 4 + 7 + 1); the new files 44, 21 and 28 cases. A host that cannot create a junction skips X7c, X12d, X16, C7[junction] and C11[junction], as it skipped X7 and C7. **A4 expected (analysis):** M1's list 699 passed and 1 skipped (693 + 6: X17, X17b, X18, X19 ×3), M2's 593 and 1 (587 + 6), M3's 699 and 1 (690 + 6 + 3: C14 ×2, C15); the new files 50, 21 and 31 cases. A host that cannot create a junction also skips C14[tier2, tier3]. **A5 expected (analysis):** M1's list 700 passed and 1 skipped (699 + X17c), M2's 594 and 1, M3's 700 and 1; the new files 51, 21 and 31 cases. X18 passes on M1's stage alone: it scans `knowledge/nature_description.py` only once that file exists.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `archive_snapshots`, `nature_clearances` in `ArchiveStore._SCHEMA` | `ArchiveStore.initialize` (creates them); `ArchiveLedger`; the store registry's baseline row (7.4, 7.14); `_counts`-style tests that name their tables (`test_ad1341_s3_veto_store.py:38`: a fixed list, unaffected) | additive |
| `ArchiveLedger` and its records | `__main__.py` only (X13, C8 census) | new |
| `records_snapshot` | `__main__.py` only (X13: no other module imports it) | new |
| `_promote_into_archive`'s message | `_promote_before_reset` prints it; S1 to S5 tests assert substrings of its first line, which is unchanged (`test_ad1341_s3_review_cli.py:125`, `:135`); S6's notes are separate lines | additive |
| The no-id branch at tier 3 | the reset only | refuses where Ship's Records hold files |
| `SourceKind.NATURE_DESCRIPTION` | `promote_entry` (TEXT), `source_state`, `veto_source`, `_pending_label`, `probos archive veto` (`.value`), S1's closed-set pin (7.11); no `src` code switches on kinds outside `archive_promotion.py`'s records rules (grep in §11) | a new kind |
| `promote_nature_description` | `__main__._describe_nature` | the one writer of the kind |
| `review_nature_description` | `__main__._pending_nature` (`probos archive pending`); keeps S3's census (`test_ad1341_s3_veto_store.py:517`: only `archive_promotion.py` names `source_state`) | a read |
| `_show_promotion_plan(..., tier=)` | `_cmd_reset` (its one caller, Absence S6-AV5) | keyword with default |
| `_show_confirmation_prompt`, `_show_dry_run` `clean_slate=` | `_cmd_reset` (their one callers, Absence S6-AV5) | keyword with default |
| `args.clean_slate` | `_cmd_reset` via `getattr(..., False)`: every Namespace built by older tests lacks it | default off |
| The reset summary's two new lines | the Captain's console; no test pins the summary (§11) | additive |
| `_reset_preflight` (A2) | `_cmd_reset` only: the reset (exit 1 before the confirmation) and the dry run (a warning, exit 0) | new refusals, earlier |
| `_archive_reset_overlap` (A2: the snapshots directory; `clean_slate=`) | `_cmd_reset` only (A2-AV1); its message's second line changes, the first (asserted at `test_ad1341_s1_reset_and_erase.py:785`) does not | refuses in new cases |
| `_promote_before_reset` / `_promote_into_archive` return the generation's close (A2) | `_cmd_reset` / `_promote_before_reset` only; no test calls either (A2-AV1) | private signature |
| `records_snapshot.lstat_or_none`, `is_link_status`, `is_link_or_junction` (A2) | `records_snapshot` itself and `__main__.py` (X13 holds) | new |
| `archive_promotion._nature_state` (A2) | `promote_nature_description`, `review_nature_description` | private |
| `records_snapshot.temporary_name`, `retained_alias`, `_IO_REPARSE_TAG_MOUNT_POINT` (A4) | `prepare_snapshot`; `__main__._erase_snapshot`, `__main__._snapshot_file_problem` (A5) (X13 holds: only `__main__.py` imports the module) | new |
| `is_link_status` (A4: the module's constant) | `plan_snapshot`, `is_link_or_junction`, `__main__._nature_dir_problem`; through them `_reset_preflight`, `prepare_snapshot`, `_snapshot_file_problem` | the same results on Windows; no `AttributeError` on POSIX |
| `_cmd_reset`'s dry run with a refusal (A4) | the Captain's console; X14, X14b and C14 assert the refusal's text, which is kept; no test asserts the table or plan beside a refusal (A4-AV3) | prints only the refusal; exit 0 (it was 0, or 1 when the plan could not be read) |
| `_show_promotion_plan` without `snapshot=` (A4) | `_cmd_reset`, its one caller (A4-AV2) | keyword removed |
| `_snapshot_state` (A4: an erased row whose file remains) | `probos archive snapshots`; X12 asserts `(erased by the Captain);` after the file is gone (A4-AV5) | display |
| the skip's message (A4, M3) | `_promote_before_reset` prints it; no test pins it (A4-AV4) | wording |

## 6. Tests

On each milestone's base, every test in its new file fails at import:
- M1: `ImportError: cannot import name 'records_snapshot' from 'probos.knowledge'` (its first S6 import is `from probos.knowledge import records_snapshot`).
- M2: `ImportError: cannot import name 'NATURE_DESCRIPTION_PREFIX' from 'probos.knowledge.archive_promotion'`.
- M3: `ImportError: cannot import name 'NatureClearanceRecord' from 'probos.knowledge.archive_ledger'`.

The last column is the assertion each test fails at once the names exist but the behaviour is the base's (analysis, not a run). "(new)" means wholly new behaviour.

**M1, `tests/test_ad1341_s6_records_snapshot.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| X1 | `test_a_full_reset_keeps_ship_records_as_one_checked_bag_before_it_deletes_them` | the real seam: producers write, the real reset snapshots, the row, the bag read back byte for byte, RA3-1's file named, the generation closed, a later crew's Oracle reads none of it | `(snapshot,) = _snapshot_files(tmp_path)` (base: none) |
| X2 | `test_a_tier2_reset_keeps_ship_records_and_takes_no_snapshot` | D3: tier 2 snapshots nothing | `archive_snapshots` does not exist (base) |
| X3 | `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing[10 faults]` | D5, D6: link, both bounds, grew, shrank, unreadable, reads back wrong, member missing, row refused; A2: the three the preflight knows (link, both bounds) leave the archive unopened; A3: a member the bag does not list (`member-extra`, P-8's one killer) | `== 1` (base: 0); on `f9afeb59`, `not _archive_db(tmp_path).exists()` for the three; `member-extra` passes on `f9afeb59` and `47568aa7` (it pins the member-list check) |
| X4 | `test_skip_promotion_skips_the_snapshot_with_it_and_says_so` | D8 | the "skipped with it" line |
| X5 | `test_without_an_instance_id_a_full_reset_of_ship_records_refuses` | D8; tier 2 unchanged | `== 1` |
| X6 | `test_the_plan_lists_every_file_but_git_and_procedures_within_its_bounds` | D3, D5: the exclusions are top-level only; at both bounds and one beyond; missing root; a root that is a file; an empty tree writes nothing | (new) |
| X7 | `test_a_link_inside_ship_records_is_never_followed` | D5 (junction on Windows, symlink elsewhere; skips where the host refuses) | (new) |
| X8 | `test_a_prepared_snapshot_reads_back_as_written_and_is_published_once` | D2, D4: name, temporary then final, SHA-256, manifest percent-encoding, bag-info | (new) |
| X9 | `test_a_snapshot_is_never_written_over` | D5: at prepare and at publish | (new) |
| X10 | `test_an_instance_id_that_cannot_name_a_directory_refuses_the_snapshot[9]` and `test_only_a_snapshot_s_own_name_is_a_snapshot_path` | D4, D7 | (new) |
| X11 | `test_the_ledger_records_a_snapshot_without_its_content_and_marks_its_erasure_once` and `test_the_ledger_opens_only_an_archive_the_store_has_brought_to_its_schema` | D7: a second mark keeps the first reason and time (the one killer of P-18) | (new) |
| X12 | `test_the_captain_lists_and_erases_a_snapshot_with_the_marker_first` | D7: list, decline, a failed unlink (marker kept), the rerun, the first reason stands (by the CLI's own `erased_at` check, which never reaches the ledger's guard; X11 pins that) | (new) |
| X12b | `test_an_erasure_never_deletes_a_file_outside_the_snapshots` | D7: a tampered row; disabled archive; bad id or reason | (new) |
| X12c | `test_main_parses_the_snapshot_commands[2]` | the parser | (new) |
| X13 | `test_only_the_cli_records_or_erases_a_snapshot_and_nothing_else_reads_one` | D3, D7: census | (new) |
| X14 | `test_a_dry_run_shows_the_snapshot_a_full_reset_would_keep_and_writes_nothing` | dry run, and its refusal | the "Ship's Records snapshot:" line |
| X3b | `test_a_publish_that_fails_leaves_its_row_shown_missing_and_deletes_nothing` | A2 (A-F7): the row stays, never deleted, shown `(missing)`; nothing deleted; no generation | passes on `f9afeb59` (pins the protocol) |
| X7b | `test_a_ship_records_root_that_cannot_be_inspected_refuses` | A2 (A-F1) | `pytest.raises(PermissionError)`: DID NOT RAISE |
| X7c | `test_a_ship_records_root_that_is_a_link_is_never_followed` | A2 (A-F1): plan and reset | `pytest.raises(SnapshotRefused, match="is a link")`: DID NOT RAISE |
| X8b | `test_a_tag_file_that_reads_back_wrong_refuses_the_snapshot` | A2 (A-F6) | DID NOT RAISE |
| X9 | (extended) `test_a_snapshot_is_never_written_over` | A2 (A-F4): a name that appears after every check | `racing.publish()`: DID NOT RAISE |
| X9b | `test_a_file_system_without_hard_links_refuses_to_publish` | A2 (A-F4): fail closed, never a rename | DID NOT RAISE |
| X12d | `test_an_erasure_deletes_only_a_regular_file_inside_the_snapshots_directory` | A2 (A-F3) | `_erasures(tmp_path) == [(None, "")]` (base: marked) |
| X14b | `test_a_dry_run_says_a_full_reset_without_an_instance_id_would_refuse` | A2 (A-F5); A4: a refused dry run shows no tier table | `"This reset would refuse" in out`; on `2a1b6319`, `"Institutional Knowledge" not in out` |
| X16 | `test_a_snapshot_is_written_only_into_the_snapshots_directory_itself` | A2 (A-F2): prepare, the tier 3 preflight, the tier 2 overlap | `pytest.raises(SnapshotRefused, match="is a link")`: DID NOT RAISE |
| X17 | `test_an_erasure_removes_the_temporary_name_a_publish_could_not` | A4 (A-R2-F2): the alias removed first; unfinished while either remains (exit 1, the listing says so); the rerun finishes it | on `2a1b6319`, the first erasure's `== 1` (base: 0, the alias left readable) |
| X17b | `test_an_erasure_leaves_a_temporary_name_that_is_another_file` | A4: identity, not name or content (P-40's one killer) | passes on `2a1b6319` (a control) |
| X17c | `test_an_erasure_refuses_a_temporary_name_whose_identity_cannot_be_shown` | A5 (A-R3-F1): every index reported as 0 (injected at `records_snapshot.lstat_or_none`) with another file at the temporary name: exit 1 before the marker, both names and the row unchanged; once that file is removed by hand, the rerun erases (a zero index with no temporary name is unaffected); P-44's and P-45's one killer | on `77b65917`, the first erasure's `== 1` (exit 0, the other file removed) |
| X18 | `test_a_status_is_judged_by_its_mode_and_only_a_junction_s_tag` | A4 (A-R2-F1): POSIX-shaped statuses with a POSIX build's `stat`; a junction's tag; a cloud placeholder's tag; no S6 module names a Windows-only `stat` attribute (A5: `nature_description.py` once M2 adds it) | the directory case: `AttributeError` (`IO_REPARSE_TAG_MOUNT_POINT`) |
| X19 | `test_a_full_reset_its_dry_run_and_an_erasure_need_no_windows_only_name[full, dry-run, erasure]` | A4 (A-R2-F1): the real commands with a POSIX build's `stat` | full and dry-run: `AttributeError` raised by `_reset`; erasure: `== 0` (base: 1, "The erasure failed") |

**M2, `tests/test_ad1341_s6_nature_description.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| N1 | `test_a_reset_archives_one_description_of_what_this_crew_developed_never_the_procedures` | the real seam: exact content, listed by completions and not by creation (a premise assertion pins that the two orders differ: D-6), provenance, no steps, the store unchanged, the generation's counts, a later crew reads it labelled "generation 1" | the archive's rows (base: none) |
| N2 | `test_a_description_at_its_bound_reaches_a_later_crew_whole_through_the_oracle_tool[2]` | D10: 900 characters, "And N more", the real tool, worst label | (new) |
| N3 | `test_nothing_to_describe_archives_nothing_and_creates_no_store[3]` | D10: no store (and none created), nothing since boot, no instance id | (new) |
| N4 | `test_text_from_the_store_is_one_line_without_control_or_format_characters[7]` | D10 | (new) |
| N5 | `test_the_captain_reviews_and_vetoes_a_description_before_the_reset` | D11: one builder; the store changes between the review and the reset; A2 (B-F1): `pending` and the veto print the whole text | `+ would be promoted: nature-description/...`; on `f9afeb59`, `f"    {line}" in out` |
| N6 | `test_a_procedure_store_that_cannot_be_read_refuses_the_reset_and_deletes_nothing` | D6, D10 | `== 1` |
| N7 | `test_only_a_nature_description_without_episodes_is_promoted_as_one` | D10: the writer's guards, idempotence | (new) |
| N8 | `test_the_dry_run_shows_the_description_the_reset_would_archive` | D11 | the description's lines |
| N9 | `test_a_retried_reset_keeps_one_description_per_generation` | A2 (B-F2): through the real reset and `pending` | `"  = already archived (entry 1): ..." in out` (base: a revision) |
| N9b | `test_one_description_per_generation_whatever_its_content` | A2 (B-F2): the writer and the review | `is PromotionOutcome.PRESENT` (base: CREATED) |
| N10 | `test_a_full_reset_whose_snapshot_fails_archives_no_description` | A2 (B-F2): archived after the snapshot | `== [(0,)]` (base: 1) |
| N11 | `test_a_wal_mode_store_is_described_and_its_database_bytes_are_unchanged` | A2 (B-F4): the narrowed claim | passes on `f9afeb59` |

**M3, `tests/test_ad1341_s6_clean_slate.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| C1 | `test_a_clean_slate_describes_records_and_clears_nature_and_touches_nothing_else[tier2, tier3]` | D12, D13: the real seam; marker; description first; every other file byte-identical; an earlier archive entry kept | `not (data_dir / "procedures").exists()` |
| C2 | `test_without_clean_slate_nature_persists_at_every_tier[3]` | D12 | the "Nature kept" line |
| C3 | `test_a_clean_slate_that_does_not_apply_or_cannot_be_recorded_changes_nothing[2]` | D12, D13: `--soft`; archive disabled | `== 2` |
| C4 | `test_an_interrupted_clean_slate_is_finished_by_running_it_again` | D13: recovery; A2 (C-F3): no generation is closed until the clearance finishes | `== 1`; on `f9afeb59`, `generations == [(0,)]` |
| C5 | `test_a_clean_slate_whose_marker_cannot_be_written_deletes_nothing` | D13 | `== 1` |
| C6 | `test_the_dry_run_and_the_confirmation_name_what_a_clean_slate_clears` | D13 | the "Nature (--clean-slate)" row |
| C7 | `test_a_link_or_a_file_at_the_procedures_name_is_refused_before_anything_is_written[junction, file]` | D12; A2 (B-F3, C-F2): every archive table unchanged | `_archive_state(tmp_path) == archive_before` |
| C8 | `test_only_the_cli_records_a_clean_slate` | census | (new) |
| C9 | `test_main_parses_clean_slate` | the parser | argparse error (base) |
| C10 | `test_a_clean_slate_marker_holds_only_what_it_may[8]` | D13 | (new) |
| C11 | `test_the_clearance_refuses_a_link_or_a_file_again_where_it_deletes[junction, file]` | A2: the check repeated where it deletes | passes on `f9afeb59` |
| C12 | `test_an_archive_inside_the_procedure_store_refuses_a_clean_slate[tier2, tier3, flag-off]` | A2 (C-F1) | the dry run's `== 1` (base: 0) |
| C13 | `test_a_skipped_promotion_is_closed_only_after_its_clean_slate` | A2 (C-F3) with `--skip-promotion`; A4 (C-R2-F2): the message says the reason will be recorded | `== [(0,)]` (base: 1); on `2a1b6319`, `"the reason is recorded" not in out` |
| C14 | `test_a_refused_dry_run_reads_nothing_through_the_procedures_link[tier2, tier3]` | A4 (R2-B1, C-R2-F1): a WAL-mode store behind a junction: zero opens, no sizing, no sidecars, none of its text | on `2a1b6319`, `opened == []` (base: one open) |
| C15 | `test_a_clean_slate_needs_no_windows_only_name` | A4 (A-R2-F1) | on `2a1b6319`, `AttributeError` raised by `_reset` |

## 7. The contract

### 7.1 New file: `src/probos/knowledge/records_snapshot.py` (M1)

```python
"""AD-1341 S6 (#1569): the Ship's Records snapshot a ``--full`` reset keeps before it deletes Ship's Records.

AD-524's unbuilt item (1). Before a tier 3 reset deletes ``{data_dir}/ship-records``, ``probos reset`` copies every
regular file in it, byte for byte, into one ZIP file beside the Ship's Archive:
``{archive_dir}/ship-records-snapshots/{timeline_id}/{started}_{ended}.zip``, keyed by the ship's instance id (the
ship's DID is ``did:probos:{timeline_id}``) and the generation's dates. Inside is one BagIt bag (RFC 8493) named after
the file: ``bagit.txt``, ``bag-info.txt``, ``manifest-sha256.txt`` and the payload under ``data/``, so an extracted
snapshot can be checked by any BagIt validator.

- A snapshot is the Captain's copy, never knowledge. No agent, service or Oracle tier reads it and it is not an
  archive entry, so it holds every classification, as Ship's Records do. ``archive_ledger`` records it, and only the
  Captain's ``probos archive erase-snapshot`` removes it.
- Two top-level directories are left out: ``.git`` (the history; the working tree is what the promotion read) and
  ``procedures`` (the Cognitive JIT procedures' YAML copies: a procedure's body stays in its store, as nature).
- Every other entry must be a regular file or a directory that can be read now. A link or junction (never followed),
  a special file, a file that cannot be read, or one whose size changes while it is copied refuses the snapshot, and
  with it the reset, before anything is deleted. So does a tree of more than ``SNAPSHOT_MAX_FILES`` files or
  ``SNAPSHOT_MAX_BYTES`` bytes. AD-1341 S6 A2: so does a root that is a link or junction or cannot be inspected (only
  a root that is not there is an empty plan), and a link or junction at the snapshots directory or the timeline's
  directory the snapshot is written into.
- The file is written under a temporary name beside its final one, flushed to disk, read back and checked against
  what was written (every member, the tag files too), and only then published (``PreparedSnapshot.publish``: one hard
  link to the final name, which never replaces a name on Windows or POSIX, then the temporary name is removed). No
  snapshot is ever written over; a file system without hard links refuses (fail closed). A file's modification time
  is not kept: every member carries the snapshot's time.
- Synchronous: the offline reset is its one caller.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

#: The directory beside the Ship's Archive's database that holds the snapshots.
SNAPSHOT_DIR_NAME = "ship-records-snapshots"

#: The top-level Ship's Records directories a snapshot leaves out (the module docstring says why).
SNAPSHOT_EXCLUDED = (".git", "procedures")

#: A larger tree refuses the snapshot, and the reset with it; ``--skip-promotion REASON`` skips both.
SNAPSHOT_MAX_FILES = 100_000
SNAPSHOT_MAX_BYTES = 2 * 1024**3

_BAGIT_TXT = "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
_CHUNK = 1024 * 1024
_STAMP = "%Y%m%dT%H%M%SZ"
_TIMELINE = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_TIMELINE_SEGMENT = re.compile(_TIMELINE)
_RELATIVE_PATH = re.compile(rf"{_TIMELINE}/\d{{8}}T\d{{6}}Z_\d{{8}}T\d{{6}}Z\.zip")

_ZipStamp = tuple[int, int, int, int, int, int]

#: AD-1341 S6 A4 (A-R2-F1): a junction's reparse tag, IO_REPARSE_TAG_MOUNT_POINT's documented value (MS-FSCC
#: 2.1.2.1). The ``stat`` module defines that name on Windows builds only, so the value is this module's own.
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


class SnapshotRefused(Exception):
    """What a snapshot cannot hold or cannot read. The reset refuses, and nothing is deleted."""


@dataclass(frozen=True)
class SnapshotFile:
    """One regular file a snapshot holds: its path under the Ship's Records root ("/"-separated) and its size."""

    path: str
    size: int


@dataclass(frozen=True)
class SnapshotPlan:
    """What a snapshot of a Ship's Records root would hold, in path order. Building it opens no file."""

    files: tuple[SnapshotFile, ...]
    total_bytes: int


@dataclass(frozen=True)
class SnapshotResult:
    """A checked snapshot: its path under ``SNAPSHOT_DIR_NAME``, the ZIP file's SHA-256, and what it holds."""

    relative_path: str
    sha256: str
    file_count: int
    total_bytes: int
    generation_started: str
    generation_ended: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class PreparedSnapshot:
    """A snapshot written and checked under its temporary name. ``publish`` puts it in place; ``discard`` removes it."""

    result: SnapshotResult
    temp_path: Path
    final_path: Path

    def publish(self) -> None:
        """A hard link from the temporary name to the final one, then the temporary name is removed (A2, A-F4).

        ``os.link`` never replaces an existing name, on Windows and POSIX alike, so a file that appears at the final
        name at any moment is never written over: it refuses. A file system without hard links refuses too (fail
        closed: never a rename that may replace). Once the link exists the snapshot is in place; a temporary name that
        cannot then be removed is logged, not raised: it is the same file under a second name, which the Captain's
        erasure removes first (A4, ``retained_alias``).
        """
        try:
            os.link(self.temp_path, self.final_path)  # A2: no-replace on Windows and POSIX; an existing name refuses
        except FileExistsError:
            raise SnapshotRefused(f"a snapshot named {self.result.relative_path} exists already") from None
        except OSError as exc:
            raise SnapshotRefused(
                f"the snapshot cannot be published without a hard link on this file system ({exc}); keep the Ship's "
                "Archive on a file system that has them, or pass --skip-promotion REASON"
            ) from exc
        _remove_quietly(self.temp_path)

    def discard(self) -> None:
        """Remove the temporary file, if it is still there."""
        _remove_quietly(self.temp_path)


def is_snapshot_relative_path(value: object) -> bool:
    """Whether ``value`` is a snapshot's name as ``snapshot_relative_path`` builds it: one directory, one ZIP file."""
    return type(value) is str and _RELATIVE_PATH.fullmatch(value) is not None


def snapshot_relative_path(timeline_id: str, started: datetime, ended: datetime) -> str:
    """``{timeline_id}/{started}_{ended}.zip``, both in UTC. An instance id that cannot name a directory refuses."""
    if type(timeline_id) is not str or _TIMELINE_SEGMENT.fullmatch(timeline_id) is None:
        raise SnapshotRefused("the ship's instance id cannot name a snapshot directory (1-64 letters, digits, . _ -)")
    return f"{timeline_id}/{_stamp(started)}_{_stamp(ended)}.zip"


def lstat_or_none(path: Path) -> os.stat_result | None:
    """AD-1341 S6 A2: ``os.lstat(path)``, never following a link; None only when nothing is there.

    Any other ``OSError`` propagates: a path that cannot be inspected is never taken for a missing one (A-F1).
    """
    try:
        return os.lstat(path)
    except FileNotFoundError:  # only absence is None (A2, A-F1)
        return None


def is_link_status(status: os.stat_result) -> bool:
    """AD-1341 S6 A2: whether an ``lstat`` result is a symbolic link or a Windows junction (D5's rule, one place).

    A4 (A-R2-F1): it names nothing a POSIX build lacks. The ``stat`` module has the junction's tag on Windows builds
    only, so the comparison uses this module's constant; a POSIX status has no tag and is judged by its mode.
    """
    reparse_tag = getattr(status, "st_reparse_tag", 0)  # a Windows-only field; POSIX has none
    return stat.S_ISLNK(status.st_mode) or reparse_tag == _IO_REPARSE_TAG_MOUNT_POINT  # A4: no Windows-only name


def is_link_or_junction(path: Path) -> bool:
    """AD-1341 S6 A2: whether ``path`` is a link or junction. False when nothing is there; other errors propagate."""
    status = lstat_or_none(path)
    return status is not None and is_link_status(status)


def temporary_name(final: Path) -> Path:
    """AD-1341 S6 A4: the name a snapshot is written and checked under before ``publish``: ``.{name}.partial``."""
    return final.with_name(f".{final.name}.partial")


def retained_alias(final: Path) -> Path | None:
    """AD-1341 S6 A4 (A-R2-F2): the temporary name ``publish`` could not remove after its link, or None.

    ``publish`` links the final name, then removes the temporary one; a removal that fails (a sharing violation on
    Windows) leaves the snapshot's own file under a second name. It is named here only when it is that file: both
    names are read with ``lstat``, never followed, and share a device and file id (``os.path.samestat``). Another
    attempt's temporary file, a copy with equal bytes, a link or a directory there is another file and is never
    named. None when either name is absent; any other ``OSError`` propagates.

    A5 (A-R3-F1): ``samestat`` compares ``st_dev`` and ``st_ino`` only, and ``st_ino`` identifies a file only when it
    is nonzero, so two indices of 0 prove nothing. When both names exist and either index is 0, this raises
    ``SnapshotRefused``: the erasure keeps both names and refuses; it never guesses.
    """
    alias = temporary_name(final)
    final_status, alias_status = lstat_or_none(final), lstat_or_none(alias)
    if final_status is None or alias_status is None:
        return None
    if not (final_status.st_ino and alias_status.st_ino):  # A5 (A-R3-F1): an index of 0 identifies no file
        raise SnapshotRefused(
            f"{alias} is beside the snapshot, and this file system reports no usable file index, so whether "
            "it is the snapshot's own file cannot be shown; both names are kept: check it, remove it by hand, "
            "then run the command again"
        )
    return alias if os.path.samestat(final_status, alias_status) else None  # one file under two names


def plan_snapshot(root: Path) -> SnapshotPlan:
    """Every regular file a snapshot of ``root`` would hold, in path order. Reads names and sizes; opens no file.

    Only a root that is not there is an empty plan (a vessel with no Ship's Records); a root that cannot be inspected
    propagates its ``OSError``, and a root that is a link or junction refuses (A2, A-F1). A link or junction, a special
    file or a tree beyond the bounds refuses. Any ``OSError`` propagates: a directory that cannot be listed is never
    taken for an empty one (an explicit walk, as S4 A5 chose over ``os.walk``, which swallows them).
    """
    root_status = lstat_or_none(root)
    if root_status is None:
        return SnapshotPlan(files=(), total_bytes=0)
    if is_link_status(root_status):  # the root itself is never followed either (A2)
        raise SnapshotRefused(f"Ship's Records at {root} is a link; a snapshot copies only what Ship's Records hold")
    if not stat.S_ISDIR(root_status.st_mode):
        raise SnapshotRefused(f"Ship's Records at {root} is not a directory")
    files: list[SnapshotFile] = []
    total = 0
    pending: list[tuple[str, str]] = [("", str(root))]
    while pending:
        prefix, directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = f"{prefix}{entry.name}"
                if entry.is_symlink() or entry.is_junction():  # never followed: it may lead out of Ship's Records
                    raise SnapshotRefused(f"{relative} is a link; a snapshot copies only what Ship's Records hold")
                if entry.is_dir(follow_symlinks=False):
                    if not (prefix == "" and entry.name in SNAPSHOT_EXCLUDED):  # .git/ and procedures/ stay out
                        pending.append((f"{relative}/", entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise SnapshotRefused(f"{relative} is not a regular file")
                size = entry.stat(follow_symlinks=False).st_size
                files.append(SnapshotFile(path=relative, size=size))
                total += size
                if len(files) > SNAPSHOT_MAX_FILES or total > SNAPSHOT_MAX_BYTES:
                    raise SnapshotRefused(
                        f"Ship's Records exceed the snapshot's bound of {SNAPSHOT_MAX_FILES} files and "
                        f"{SNAPSHOT_MAX_BYTES} bytes"
                    )
    files.sort(key=lambda item: item.path)
    return SnapshotPlan(files=tuple(files), total_bytes=total)


def prepare_snapshot(
    root: Path, snapshots_dir: Path, *, timeline_id: str, ship_did: str, started: datetime, ended: datetime,
) -> PreparedSnapshot | None:
    """Write and check a snapshot of ``root`` under a temporary name; None when ``root`` holds no file to keep.

    Raises ``SnapshotRefused`` for what the snapshot cannot hold, and any ``OSError`` or ``zipfile`` error as it comes.
    The temporary file is removed on every failure, and nothing is ever written at the final name here.
    """
    relative = snapshot_relative_path(timeline_id, started, ended)
    plan = plan_snapshot(root)
    if not plan.files:
        return None
    final = snapshots_dir / relative
    for directory in (snapshots_dir, final.parent):
        if is_link_or_junction(directory):  # A2: written only into the snapshots directory itself
            raise SnapshotRefused(f"{directory} is a link or junction; a snapshot is written only into its own directory")
    if os.path.lexists(final):  # a snapshot is never written over
        raise SnapshotRefused(f"a snapshot named {relative} exists already")
    info = _bag_info(plan, timeline_id=timeline_id, ship_did=ship_did, started=started, ended=ended)
    final.parent.mkdir(parents=True, exist_ok=True)
    temp = temporary_name(final)  # A4: one builder of the name, which the erasure also looks for
    bag = final.stem
    stamp: _ZipStamp = tuple(_utc(ended).timetuple()[:6])  # type: ignore[assignment]
    raw = open(temp, "xb")  # exclusive: never another attempt's file  # noqa: SIM115
    try:
        with raw:
            digests = _write_bag(raw, root, bag, plan, info, stamp)
            raw.flush()
            os.fsync(raw.fileno())
        sha256 = _verify_bag(temp, bag, plan, digests)
    except BaseException:
        _remove_quietly(temp)
        raise
    return PreparedSnapshot(
        result=SnapshotResult(
            relative_path=relative, sha256=sha256, file_count=len(plan.files), total_bytes=plan.total_bytes,
            generation_started=_iso(started), generation_ended=_iso(ended),
            paths=tuple(item.path for item in plan.files),
        ),
        temp_path=temp,
        final_path=final,
    )


def _write_bag(
    raw: BinaryIO, root: Path, bag: str, plan: SnapshotPlan, info: str, stamp: _ZipStamp,
) -> dict[str, str]:
    """The bag's payload, then its manifest, ``bag-info.txt`` and ``bagit.txt``; each payload file's SHA-256."""
    digests: dict[str, str] = {}
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bag_zip:
        for item in plan.files:
            digests[item.path] = _copy_member(bag_zip, root / item.path, f"{bag}/data/{item.path}", item, stamp)
        manifest = "".join(f"{digests[item.path]}  data/{_bagit_path(item.path)}\n" for item in plan.files)
        _write_text(bag_zip, f"{bag}/manifest-sha256.txt", manifest, stamp)
        _write_text(bag_zip, f"{bag}/bag-info.txt", info, stamp)
        _write_text(bag_zip, f"{bag}/bagit.txt", _BAGIT_TXT, stamp)
    return digests


def _copy_member(
    bag_zip: zipfile.ZipFile, source: Path, name: str, item: SnapshotFile, stamp: _ZipStamp,
) -> str:
    """Copy one file into the bag, hashing what is read. A size other than the listed one refuses."""
    member = zipfile.ZipInfo(name, date_time=stamp)
    member.compress_type = zipfile.ZIP_DEFLATED
    digest = hashlib.sha256()
    copied = 0
    with open(source, "rb") as reader, bag_zip.open(member, "w", force_zip64=True) as writer:
        while chunk := reader.read(_CHUNK):
            copied += len(chunk)
            if copied > item.size:  # it grew after it was listed; stop reading it
                raise SnapshotRefused(f"{item.path} changed while it was copied")
            digest.update(chunk)
            writer.write(chunk)
    if copied != item.size:  # it shrank after it was listed
        raise SnapshotRefused(f"{item.path} changed while it was copied")
    return digest.hexdigest()


def _write_text(bag_zip: zipfile.ZipFile, name: str, text: str, stamp: _ZipStamp) -> None:
    member = zipfile.ZipInfo(name, date_time=stamp)
    member.compress_type = zipfile.ZIP_DEFLATED
    bag_zip.writestr(member, text.encode("utf-8"))


def _verify_bag(temp: Path, bag: str, plan: SnapshotPlan, digests: dict[str, str]) -> str:
    """Read the written file back: its members in order, each payload file's SHA-256; return the file's SHA-256."""
    expected = [f"{bag}/data/{item.path}" for item in plan.files]
    expected += [f"{bag}/manifest-sha256.txt", f"{bag}/bag-info.txt", f"{bag}/bagit.txt"]
    with zipfile.ZipFile(temp) as bag_zip:
        if bag_zip.namelist() != expected:
            raise SnapshotRefused("the snapshot read back does not list what was written")
        for item in plan.files:
            if _digest(bag_zip.open(f"{bag}/data/{item.path}")) != digests[item.path]:  # zipfile also checks each CRC
                raise SnapshotRefused(f"{item.path} does not read back as it was written")
        for name in expected[len(plan.files):]:  # A2: the tag files too, read whole, so zipfile checks each CRC
            _digest(bag_zip.open(name))
    return _digest(open(temp, "rb"))  # noqa: SIM115 -- closed by _digest


def _digest(stream: BinaryIO) -> str:
    """The SHA-256 of a stream, read in chunks; the stream is closed."""
    digest = hashlib.sha256()
    with stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _bag_info(plan: SnapshotPlan, *, timeline_id: str, ship_did: str, started: datetime, ended: datetime) -> str:
    """``bag-info.txt``: RFC 8493's reserved elements, then ProbOS's own (the ship, its timeline and dates)."""
    if type(ship_did) is not str or not ship_did.strip() or not ship_did.isprintable():
        raise SnapshotRefused("the ship's DID cannot stand in the snapshot's metadata")
    return (
        f"Bagging-Date: {_utc(ended):%Y-%m-%d}\n"
        f"Payload-Oxum: {plan.total_bytes}.{len(plan.files)}\n"
        f"External-Identifier: {ship_did}\n"
        f"ProbOS-Timeline: {timeline_id}\n"
        f"ProbOS-Generation-Started: {_iso(started)}\n"
        f"ProbOS-Generation-Ended: {_iso(ended)}\n"
        f"ProbOS-Excluded: {' '.join(name + '/' for name in SNAPSHOT_EXCLUDED)}\n"
        "ProbOS-Source: AD-1341 S6, probos reset --full\n"
    )


def _bagit_path(path: str) -> str:
    """RFC 8493 2.1.3: a manifest path percent-encodes "%", CR and LF, and only those."""
    return path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _utc(moment: datetime) -> datetime:
    if type(moment) is not datetime or moment.tzinfo is None:
        raise ValueError("AD-1341 S6: a snapshot's times are datetimes with an offset")
    return moment.astimezone(UTC)


def _stamp(moment: datetime) -> str:
    return _utc(moment).strftime(_STAMP)


def _iso(moment: datetime) -> str:
    return _utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _remove_quietly(path: Path) -> None:
    """Remove a temporary file. A failure is logged, never raised over the error that led here."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("AD-1341 S6: the temporary snapshot %s could not be removed", path, exc_info=True)
```

The in-loop `copied > item.size` guard has an outcome-equivalent mutant (the check after the loop refuses too); it bounds how much of a growing file is read, so it has no §10 row (register R24). The `is_file` refusal is reachable only with a special file (a FIFO, POSIX), so it is tested on POSIX only (X6 has no such case; register R23) and has no row.

### 7.2 New file: `src/probos/knowledge/archive_ledger.py` (M1)

```python
"""AD-1341 S6 (#1569): the reset's ledger in the Ship's Archive's file: the Ship's Records snapshots a ``--full``
reset kept.

``archive_snapshots`` holds no content: each snapshot's timeline, ship DID, generation dates, file name, the file's
SHA-256, its file count and size (``probos.knowledge.records_snapshot`` writes the file beside the archive).
``ArchiveStore`` owns the schema and its version (``archive_store._SCHEMA``). The ledger opens the same file on a
connection of its own, and only once the store has brought it to that version, so a ledger write never shares a
transaction with an entry's (S1 D16). It is its own class because ``ArchiveStore`` is at the repository's SRP method
trigger (``scripts/check_architecture_principles.py``).

- Only the offline CLI writes here: ``record_snapshot`` from ``probos reset``, ``mark_snapshot_erased`` from the
  Captain's ``probos archive erase-snapshot`` (``tests/test_ad1341_s6_records_snapshot.py`` holds that with a census).
- A snapshot's row is never deleted. The Captain's erasure marks it, with the reason and the time, before the file is
  deleted, so no snapshot is removed unrecorded; a second erasure keeps the first reason.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS, ARCHIVE_SCHEMA_VERSION
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

#: SQLite's largest rowid: no row has a larger id, and binding one raises (S1 A2, F2).
_SQLITE_MAX_ROWID = 2**63 - 1
_HEX_DIGITS = frozenset("0123456789abcdef")

_SNAPSHOT_COLUMNS = (
    "id, timeline_id, ship_did, generation_started, generation_ended, relative_path, sha256, file_count, "
    "total_bytes, recorded_at, erased_at, erase_reason"
)
_SNAPSHOT_SQL = (
    "INSERT INTO archive_snapshots (timeline_id, ship_did, generation_started, generation_ended, relative_path, "
    "sha256, file_count, total_bytes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_SNAPSHOTS_SQL = f"SELECT {_SNAPSHOT_COLUMNS} FROM archive_snapshots ORDER BY id"
_SNAPSHOT_BY_ID_SQL = f"SELECT {_SNAPSHOT_COLUMNS} FROM archive_snapshots WHERE id = ?"
# The Captain's erasure marks the row once; a second erasure keeps the first reason and time.
_SNAPSHOT_ERASE_SQL = (
    "UPDATE archive_snapshots SET erased_at = ?, erase_reason = ? WHERE id = ? AND erased_at IS NULL"
)


def _required_text(value: object, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"AD-1341 S6: {name} must be a non-empty string")


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX_DIGITS


def _valid_reason(reason: object) -> str:
    """The Captain's reason, at the archive's bound (``ARCHIVE_REASON_MAX_CHARS``), stripped."""
    if type(reason) is not str or not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        raise ValueError(f"AD-1341 S6: a reason of 1..{ARCHIVE_REASON_MAX_CHARS} characters is required")
    return reason.strip()


@dataclass(frozen=True)
class SnapshotRecord:
    """AD-1341 S6: one Ship's Records snapshot a ``--full`` reset kept, for ``archive_snapshots``. Holds no content."""

    timeline_id: str
    ship_did: str
    generation_started: str
    generation_ended: str
    relative_path: str
    sha256: str
    file_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        for name in ("timeline_id", "ship_did", "generation_started", "generation_ended", "relative_path"):
            _required_text(getattr(self, name), name)
        if not _is_sha256(self.sha256):
            raise ValueError("AD-1341 S6: sha256 is 64 lower-case hexadecimal digits")
        for count in (self.file_count, self.total_bytes):
            if type(count) is not int or count < 0:
                raise ValueError("AD-1341 S6: counts are non-negative integers")


@dataclass(frozen=True)
class SnapshotEntry:
    """AD-1341 S6: a row of ``archive_snapshots``. ``erased_at`` is set once the Captain erased the snapshot."""

    id: int
    timeline_id: str
    ship_did: str
    generation_started: str
    generation_ended: str
    relative_path: str
    sha256: str
    file_count: int
    total_bytes: int
    recorded_at: float
    erased_at: float | None = None
    erase_reason: str = ""


def _row_to_snapshot(row: Any) -> SnapshotEntry:
    return SnapshotEntry(
        id=row[0], timeline_id=row[1], ship_did=row[2], generation_started=row[3], generation_ended=row[4],
        relative_path=row[5], sha256=row[6], file_count=row[7], total_bytes=row[8], recorded_at=row[9],
        erased_at=row[10], erase_reason=row[11] or "",
    )


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it (``archive_store``'s rule, on this connection)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1341 S6: rollback after a failed ledger write found no open transaction")


class ArchiveLedger:
    """AD-1341 S6: the reset's rows in the Ship's Archive's file, on a connection of their own.

    ``initialize`` refuses a file ``ArchiveStore`` has not brought to ``ARCHIVE_SCHEMA_VERSION``: the store owns the
    schema, and its ``initialize`` creates these tables. Each write holds ``_write_lock`` from its first statement to
    its commit or rollback (S1 D16); reads take no lock. Uses the ConnectionFactory protocol.
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open the archive's file once ``ArchiveStore.initialize`` has brought it to its schema; refuse otherwise."""
        if self._db is not None:
            return
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA secure_delete=ON")  # as every connection to the archive's file does (S1)
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = int(row[0]) if row else 0
            if version != ARCHIVE_SCHEMA_VERSION:
                raise RuntimeError(
                    f"AD-1341 S6: the Ship's Archive is at schema version {version}; ArchiveStore.initialize brings "
                    f"it to {ARCHIVE_SCHEMA_VERSION} before the ledger opens it"
                )
        except BaseException:
            try:
                await db.close()
            except Exception:  # noqa: BLE001 -- the open's own failure is the one reported
                logger.debug("AD-1341 S6: closing the ledger after a failed open also failed", exc_info=True)
            raise
        self._db = db

    async def close(self) -> None:
        """Close the connection once no write is in flight."""
        async with self._write_lock:
            if self._db:
                await self._db.close()
                self._db = None

    async def record_snapshot(self, snapshot: SnapshotRecord) -> int:
        """Record a snapshot a ``--full`` reset kept; reached only from ``probos reset``. Returns the row's id.

        A second row for one file name raises (a unique index).
        """
        if type(snapshot) is not SnapshotRecord:
            raise TypeError("AD-1341 S6: record_snapshot takes a SnapshotRecord")
        params = (
            snapshot.timeline_id, snapshot.ship_did, snapshot.generation_started, snapshot.generation_ended,
            snapshot.relative_path, snapshot.sha256, snapshot.file_count, snapshot.total_bytes, time.time(),
        )
        async with self._write_lock:  # S1 D16: the row commits or rolls back alone
            if not self._db:
                raise RuntimeError("ArchiveLedger not initialized")
            try:
                cursor = await self._db.execute(_SNAPSHOT_SQL, params)
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        return cursor.lastrowid

    async def snapshot_entries(self) -> tuple[SnapshotEntry, ...]:
        """Every recorded snapshot, erased ones included, in the order they were recorded. A read."""
        if not self._db:
            raise RuntimeError("ArchiveLedger not initialized")
        cursor = await self._db.execute(_SNAPSHOTS_SQL)
        return tuple(_row_to_snapshot(row) for row in await cursor.fetchall())

    async def snapshot_by_id(self, snapshot_id: int) -> SnapshotEntry | None:
        """One recorded snapshot, or None (an id that no row can have included). A read."""
        if not self._db:
            raise RuntimeError("ArchiveLedger not initialized")
        if type(snapshot_id) is not int or snapshot_id <= 0 or snapshot_id > _SQLITE_MAX_ROWID:
            return None
        cursor = await self._db.execute(_SNAPSHOT_BY_ID_SQL, (snapshot_id,))
        row = await cursor.fetchone()
        return None if row is None else _row_to_snapshot(row)

    async def mark_snapshot_erased(self, snapshot_id: int, reason: str) -> SnapshotEntry | None:
        """The Captain's erasure of a snapshot, reached only from ``probos archive erase-snapshot``.

        Marks the row with the reason and the time before the caller deletes the file. A row already marked keeps its
        first reason. Returns the row as it now stands, or None, writing nothing, when no snapshot has this id.
        """
        if type(snapshot_id) is not int or snapshot_id <= 0:
            raise ValueError("AD-1341 S6: a snapshot id is a positive integer")
        text = _valid_reason(reason)
        async with self._write_lock:  # S1 D16: the mark and its read commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveLedger not initialized")
            if snapshot_id > _SQLITE_MAX_ROWID:
                return None
            try:
                await self._db.execute(_SNAPSHOT_ERASE_SQL, (time.time(), text, snapshot_id))
                cursor = await self._db.execute(_SNAPSHOT_BY_ID_SQL, (snapshot_id,))
                row = await cursor.fetchone()
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        if row is None:
            return None
        logger.warning("AD-1341 S6: the Captain erased Ship's Records snapshot %d", snapshot_id)
        return _row_to_snapshot(row)
```

### 7.3 `src/probos/knowledge/archive_store.py` (M1)

The table is created by the store, which owns the schema; `ArchiveStore` gains no method (D7).

**Pair 1, the module docstring.** SEARCH:
```python
manager reads ``entry_ids_citing`` and erases nothing while an entry cites an
episode it would erase, until the Captain has erased that entry.
```
REPLACE:
```python
manager reads ``entry_ids_citing`` and erases nothing while an entry cites an
episode it would erase, until the Captain has erased that entry.

AD-1341 S6: ``_SCHEMA`` also creates ``archive_snapshots``, the content-free
record of each Ship's Records snapshot a ``--full`` reset kept beside the
archive. Its rows are written by ``probos.knowledge.archive_ledger``, on a
connection of its own, never by this class.
```

**Pair 2, the schema.** SEARCH:
```python
CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_vetoes_source ON archive_vetoes(source_kind, source_ref);
"""
```
REPLACE:
```python
CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_vetoes_source ON archive_vetoes(source_kind, source_ref);

CREATE TABLE IF NOT EXISTS archive_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    ship_did TEXT NOT NULL,
    generation_started TEXT NOT NULL,
    generation_ended TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL,
    recorded_at REAL NOT NULL,
    erased_at REAL,
    erase_reason TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_snapshots_path ON archive_snapshots(relative_path);
"""
```

### 7.4 `docs/development/store-baseline.yaml` (M1)

Rule 11 (`baseline-table-drift`) of `scripts/check_store_registry.py` needs the archive store's row in `docs/development/store-baseline.yaml` to gain its new table, as S3 did for `archive_vetoes`. `archive_ledger.py` holds no `CREATE TABLE`, so it is no store of its own. SEARCH:
```yaml
- module: probos.knowledge.archive_store
  tables:
  - archive
  - archive_erasures
  - archive_vetoes
  - generations
```
REPLACE:
```yaml
- module: probos.knowledge.archive_store
  tables:
  - archive
  - archive_erasures
  - archive_snapshots
  - archive_vetoes
  - generations
```

### 7.5 `src/probos/__main__.py` (M1)

Twelve pairs, in file order (A2 added pair 1a, rewrote pair 2 and replaced pair 3; A4 rewrote pairs 2, 6, 8 and 10). `__main__.py` is not touched by S5.

**Pair 1, the annotation-only imports** (the names in the new helpers' signatures). SEARCH:
```python
    from probos.knowledge.archive_promotion import PromotionReview
    from probos.knowledge.archive_store import ArchiveStore, SourceState
    from probos.knowledge.records_store import RecordsStore
```
REPLACE:
```python
    from datetime import datetime

    from probos.knowledge.archive_ledger import ArchiveLedger, SnapshotEntry
    from probos.knowledge.archive_promotion import PendingSource, PromotionReview
    from probos.knowledge.archive_store import ArchiveStore, PromotionRecord, SourceState
    from probos.knowledge.records_snapshot import SnapshotPlan
    from probos.knowledge.records_store import RecordsStore
    from probos.protocols import DatabaseConnection
```

**Pair 1a, S1 A4's message names the snapshots too (A2).** SEARCH:
```python
        console.print(
            f"  archive.db_path is inside {overlap}; move it out of what a reset deletes. Nothing was changed.",
            markup=False,
        )
```
REPLACE:
```python
        console.print(
            f"  archive.db_path, or the snapshots directory beside it, is inside or around {overlap}; move it out of "
            "what a reset deletes. Nothing was changed.",  # AD-1341 S6 A2: the snapshots are protected too
            markup=False,
        )
```

**Pair 2, the preflight, and the dry run passes the tier (A2); a refused dry run prints the refusal and nothing else (A4).** SEARCH:
```python
    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        _show_dry_run(tier, data_dir, active_task_count, console)
        if tier >= 2:  # AD-1341 S1: the promotion plan; reads Ship's Records, opens no archive, takes no pidfile
            return _show_promotion_plan(config, data_dir, skip_reason, console)
        return 0
```
REPLACE:
```python
    # AD-1341 S6 A2: every refusal that can be known before anything is written, shared by the dry run and the reset
    refusal = _reset_preflight(config, tier, data_dir, skip_reason)

    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        if refusal:  # AD-1341 S6 A4: a reset that would refuse does nothing, so its dry run reads nothing more
            console.print("  [yellow]⚠ This reset would refuse, writing and deleting nothing:[/yellow]")
            console.print(f"    {refusal}", markup=False, emoji=False)
            console.print("\n  [dim][DRY RUN] No changes made.[/dim]")
            return 0  # AD-1341 S6 A4 (R2-B1, C-R2-F1): no tier table, plan or description reads the refused path
        _show_dry_run(tier, data_dir, active_task_count, console)
        if tier >= 2:  # AD-1341 S1: the promotion plan; reads Ship's Records, opens no archive, takes no pidfile
            return _show_promotion_plan(config, data_dir, skip_reason, console, tier=tier)
        return 0
    if refusal:  # AD-1341 S6 A2: before the confirmation, the pidfile and the promotion, so nothing is written
        console.print("[red]✗[/red] probos reset refused before writing anything:")
        console.print(f"  {refusal}", markup=False, emoji=False)
        return 1
```

**Pair 3, S1 A4's overlap protects the snapshots directory (A2, A-F2).** The no-instance-id refusal this pair added before A2 is now in `_reset_preflight` (pair 6), before anything is written. SEARCH:
```python
def _archive_reset_overlap(config: SystemConfig, tier: int, data_dir: Path, repo_path: Path) -> str:
    """What a reset of ``tier`` deletes that is, or holds, the Ship's Archive; ``""`` when nothing (A4, F3).

    The targets are what the tier loop removes for tiers 1 to ``tier``: each listed file; each listed directory,
    whose contents go; ChromaDB's UUID-named directories; the knowledge store's subdirectories (only their ``.json``
    and ``.py`` files go, but an archive there is refused too); and the instance id file. Both sides are resolved
    (symlinks, ``..``) and compared with the platform's case rule. It reads paths only and opens nothing.
    """
    from probos.config import resolve_archive_db_path

    if not config.archive.enabled:  # D13: the reset neither opens nor protects a disabled archive
        return ""
    archive = os.path.normcase(str(resolve_archive_db_path(config.archive).resolve()))
    targets: list[Path] = []
    for level in range(1, tier + 1):
        tier_def = RESET_TIERS[level]
        specials = tier_def.get("special", [])
        targets += [data_dir / name for name in [*tier_def.get("files", []), *tier_def.get("dirs", [])]]
        if "chromadb_uuid_dirs" in specials:
            targets += _find_chromadb_uuid_dirs(data_dir)
        if "knowledge_subdirs" in specials:
            targets += [repo_path / sub for sub in _RESET_SUBDIRS]
        if "ontology_instance_id" in specials:
            targets.append(data_dir / "ontology" / "instance_id")
    for target in targets:
        resolved = os.path.normcase(str(target.resolve()))
        if archive == resolved or archive.startswith(resolved.rstrip(os.sep) + os.sep):
            return str(target)
    return ""
```
REPLACE:
```python
def _archive_reset_overlap(config: SystemConfig, tier: int, data_dir: Path, repo_path: Path) -> str:
    """What a reset of ``tier`` deletes that is, or holds, the Ship's Archive or its snapshots; ``""`` when nothing.

    S1 A4 (F3): the targets are what the tier loop removes for tiers 1 to ``tier``: each listed file; each listed
    directory, whose contents go; ChromaDB's UUID-named directories; the knowledge store's subdirectories (only their
    ``.json`` and ``.py`` files go, but an archive there is refused too); and the instance id file. AD-1341 S6 A2
    (A-F2): the snapshots directory beside the archive is protected at every tier too, in both directions (inside or
    equal to a target, or a target inside it). Every side is resolved (symlinks, junctions, ``..``) and compared with
    the platform's case rule, so no link or junction aliases one into another. It reads paths only and opens nothing.
    """
    from probos.config import resolve_archive_db_path

    if not config.archive.enabled:  # D13: the reset neither opens nor protects a disabled archive
        return ""
    archive = os.path.normcase(str(resolve_archive_db_path(config.archive).resolve()))
    snapshots = os.path.normcase(str(_snapshots_dir(config).resolve()))  # AD-1341 S6 A2: the snapshots too
    targets: list[Path] = []
    for level in range(1, tier + 1):
        tier_def = RESET_TIERS[level]
        specials = tier_def.get("special", [])
        targets += [data_dir / name for name in [*tier_def.get("files", []), *tier_def.get("dirs", [])]]
        if "chromadb_uuid_dirs" in specials:
            targets += _find_chromadb_uuid_dirs(data_dir)
        if "knowledge_subdirs" in specials:
            targets += [repo_path / sub for sub in _RESET_SUBDIRS]
        if "ontology_instance_id" in specials:
            targets.append(data_dir / "ontology" / "instance_id")
    for target in targets:
        resolved = os.path.normcase(str(target.resolve()))
        within = resolved.rstrip(os.sep) + os.sep
        if archive == resolved or archive.startswith(within):
            return str(target)
        if snapshots == resolved or snapshots.startswith(within) or resolved.startswith(snapshots + os.sep):
            return str(target)  # AD-1341 S6 A2: a reset never deletes a snapshot, nor a directory that holds one
    return ""
```

**Pair 4, the audited skip covers the snapshot.** SEARCH:
```python
            await archive.record_generation(skipped)
            return True, f"Ship's Archive promotion skipped; the reason is recorded: {skip_reason.strip()}"
```
REPLACE:
```python
            await archive.record_generation(skipped)
            also = " The Ship's Records snapshot is skipped with it." if tier >= 3 else ""  # AD-1341 S6
            return True, f"Ship's Archive promotion skipped; the reason is recorded: {skip_reason.strip()}{also}"
```

**Pair 5, the snapshot before the generation's close.** SEARCH:
```python
        promoted = await promote_ship_records(records, archive, timeline_id=timeline_id)
        closed = GenerationRecord(
```
REPLACE:
```python
        promoted = await promote_ship_records(records, archive, timeline_id=timeline_id)
        notes: list[str] = []
        if tier >= 3:  # AD-1341 S6: what a --full reset deletes from Ship's Records is kept first, as one checked file
            notes.append(await _snapshot_ship_records(config, data_dir, timeline_id))
        closed = GenerationRecord(
```

**Pair 6, the notes in the message, the S6 helpers, and the dry run's signature.** SEARCH:
```python
        f"{len(promoted.withheld)} withheld (timeline {timeline_id})."
    )


def _show_promotion_plan(config: SystemConfig, data_dir: Path, skip_reason: str | None, console: Console) -> int:
```
REPLACE:
```python
        f"{len(promoted.withheld)} withheld (timeline {timeline_id})."
    ) + "".join(f"\n  {note}" for note in notes)


#: AD-1341 S6: the Ship's Records directory a tier 3 reset deletes (``RESET_TIERS[3]["dirs"]``), so the one it keeps.
_SNAPSHOT_SOURCE = "ship-records"


def _generation_started(data_dir: Path) -> datetime | None:
    """AD-1341 S6: when this ship's generation began: the modification time (UTC) of ``ontology/instance_id``, which
    the ontology loader writes once, at the ship's first boot. None when there is no instance id."""
    from datetime import UTC, datetime

    id_file = data_dir / "ontology" / "instance_id"
    if not id_file.is_file():
        return None
    return datetime.fromtimestamp(id_file.stat().st_mtime, UTC)


def _snapshots_dir(config: SystemConfig) -> Path:
    """AD-1341 S6: where Ship's Records snapshots are kept: beside the Ship's Archive's database (AD-1265's resolver)."""
    from probos.config import resolve_archive_db_path
    from probos.knowledge.records_snapshot import SNAPSHOT_DIR_NAME

    return resolve_archive_db_path(config.archive).parent / SNAPSHOT_DIR_NAME


def _snapshot_plan(data_dir: Path) -> SnapshotPlan:
    """AD-1341 S6: what a snapshot of the Ship's Records a tier 3 reset deletes would hold. Opens no file."""
    from probos.knowledge.records_snapshot import plan_snapshot

    return plan_snapshot(data_dir / _SNAPSHOT_SOURCE)


def _reset_preflight(config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None) -> str:
    """AD-1341 S6 A2: why this reset must refuse, known before anything is written; ``""`` when nothing does.

    ``_cmd_reset`` runs it before the confirmation, the pidfile and the promotion, and its dry run shows it, so a reset
    it refuses has promoted, described, snapshotted, recorded and closed nothing. At tier 3, with the archive enabled
    and no ``--skip-promotion``: the Ship's Records snapshot's plan (the root and every entry: a link, a special file,
    the bounds, a path that cannot be inspected), the instance id that keys it, and its destination (no link or
    junction at the snapshots directory or the timeline's). Reads the instance id, names and sizes; opens no
    database. The snapshot checks again where it writes (register R28).
    """
    from probos.knowledge.records_snapshot import SnapshotRefused, is_link_or_junction, snapshot_relative_path

    if tier < 3 or not config.archive.enabled or skip_reason is not None:
        return ""
    try:
        plan = _snapshot_plan(data_dir)
        if not plan.files:
            return ""
        timeline_id, started = _read_instance_id(data_dir), _generation_started(data_dir)
        if not timeline_id or started is None:  # AD-1341 S6: no ship to key the snapshot by
            return (
                f"No instance id: Ship's Records hold {len(plan.files)} file(s) a --full reset would delete with no "
                "ship to key their snapshot by. Pass --skip-promotion REASON to reset without promoting or snapshotting."
            )
        snapshot_relative_path(timeline_id, started, started)  # an instance id that cannot name a directory refuses
        for directory in (_snapshots_dir(config), _snapshots_dir(config) / timeline_id):
            if is_link_or_junction(directory):  # AD-1341 S6 A2: a snapshot is never written through a link
                return f"{directory} is a link or junction; a snapshot is written only into the snapshots directory."
    except (SnapshotRefused, OSError, ValueError) as exc:
        return f"The Ship's Records snapshot would refuse this reset: {exc}"
    return ""


def _configured_ledger(config: SystemConfig) -> ArchiveLedger:
    """AD-1341 S6: the reset's ledger in the Ship's Archive's file (the path startup opens), not yet initialised."""
    from probos.config import resolve_archive_db_path
    from probos.knowledge.archive_ledger import ArchiveLedger
    from probos.storage.sqlite_factory import default_factory

    return ArchiveLedger(str(resolve_archive_db_path(config.archive)), connection_factory=default_factory)


async def _open_ledger(config: SystemConfig) -> ArchiveLedger:
    """AD-1341 S6: the ledger, once the Ship's Archive itself has been opened (so brought to its schema) and closed."""
    archive = _configured_archive_store(config)
    await archive.initialize()
    await archive.close()
    ledger = _configured_ledger(config)
    await ledger.initialize()
    return ledger


async def _records_listing(config: SystemConfig, root: Path) -> frozenset[str]:
    """AD-1341 S6: the paths Ship's Records' own listing returns under ``root``, as the promotion's listing reads them."""
    from probos.knowledge.records_store import RecordsStore

    store = RecordsStore(config.records.model_copy(update={"repo_path": str(root)}), ontology=None)
    return frozenset(entry["path"] for entry in await store.list_entries())


async def _snapshot_ship_records(config: SystemConfig, data_dir: Path, timeline_id: str) -> str:
    """AD-1341 S6: keep what a ``--full`` reset deletes from Ship's Records as one checked snapshot; say what was kept.

    Written and checked under a temporary name, recorded in the archive's ledger, then published. Any failure removes
    the temporary file and propagates, so the reset refuses with nothing deleted. The Markdown files Ship's Records'
    own listing passes over (S1 register RA3-1: never promoted) are named, because the snapshot is where they survive.
    """
    from datetime import UTC, datetime

    from probos.identity import generate_ship_did
    from probos.knowledge.archive_ledger import SnapshotRecord
    from probos.knowledge.records_snapshot import prepare_snapshot

    root = data_dir / _SNAPSHOT_SOURCE
    started = _generation_started(data_dir)
    if started is None:  # read a moment ago as the timeline; another process removed it since
        raise RuntimeError("AD-1341 S6: ontology/instance_id disappeared during the reset")
    listed = await _records_listing(config, root)
    ship_did = generate_ship_did(timeline_id)
    prepared = prepare_snapshot(
        root, _snapshots_dir(config), timeline_id=timeline_id, ship_did=ship_did, started=started,
        ended=datetime.now(UTC),
    )
    if prepared is None:
        return "Ship's Records snapshot: Ship's Records hold no file to keep."
    result = prepared.result
    ledger = _configured_ledger(config)
    try:
        await ledger.initialize()
        snapshot_id = await ledger.record_snapshot(SnapshotRecord(
            timeline_id=timeline_id, ship_did=ship_did, generation_started=result.generation_started,
            generation_ended=result.generation_ended, relative_path=result.relative_path, sha256=result.sha256,
            file_count=result.file_count, total_bytes=result.total_bytes,
        ))
        prepared.publish()  # AD-1341 S6: recorded first, then put in place
    except BaseException:
        prepared.discard()
        raise
    finally:
        await ledger.close()
    note = (
        f"Ship's Records snapshot {snapshot_id}: {result.file_count} file(s), {result.total_bytes} bytes, kept as "
        f"{result.relative_path} beside the Ship's Archive."
    )
    unlisted = [path for path in result.paths if path.endswith(".md") and path not in listed]
    if unlisted:  # S1 register RA3-1: these were never promoted; the snapshot is where they survive
        shown = ", ".join(unlisted[:10]) + (f" and {len(unlisted) - 10} more" if len(unlisted) > 10 else "")
        note += f"\n  {len(unlisted)} Markdown file(s) Ship's Records cannot list, never promoted, are kept in it: {shown}"
    return note


def _show_snapshot_plan(config: SystemConfig, data_dir: Path, console: Console) -> None:
    """AD-1341 S6: the dry run's view of the snapshot a ``--full`` reset would keep. Reads names and sizes only."""
    from rich.markup import escape

    from probos.knowledge.records_snapshot import SnapshotRefused

    try:
        plan = _snapshot_plan(data_dir)
    except (SnapshotRefused, OSError) as exc:  # the reset itself would refuse; the dry run says so
        console.print(f"  [yellow]⚠ The Ship's Records snapshot would refuse this reset: {escape(str(exc))}[/yellow]")
        return
    if not plan.files:
        console.print("  Ship's Records snapshot: Ship's Records hold no file to keep.")
        return
    console.print(
        f"  Ship's Records snapshot: {len(plan.files)} file(s), {plan.total_bytes} bytes, would be kept in "
        f"{escape(str(_snapshots_dir(config)))} (.git/ and procedures/ left out)."
    )


def _show_promotion_plan(
    config: SystemConfig, data_dir: Path, skip_reason: str | None, console: Console, *, tier: int = 2,
) -> int:
```

**Pair 7, the dry run's skip.** SEARCH:
```python
        console.print(f"\n  Ship's Archive promotion would be skipped, recording: {escape(skip_reason.strip())}")
        return 0
```
REPLACE:
```python
        console.print(f"\n  Ship's Archive promotion would be skipped, recording: {escape(skip_reason.strip())}")
        if tier >= 3:  # AD-1341 S6
            console.print("  The Ship's Records snapshot would be skipped with it.")
        return 0
```

**Pair 8, the dry run's snapshot plan.** SEARCH:
```python
    if plan.records and not timeline_id:
        console.print("  [yellow]⚠ No instance id: this reset would refuse without --skip-promotion REASON.[/yellow]")
    return 0
```
REPLACE:
```python
    if plan.records and not timeline_id:
        console.print("  [yellow]⚠ No instance id: this reset would refuse without --skip-promotion REASON.[/yellow]")
    if tier >= 3:  # AD-1341 S6 A4: only a dry run whose preflight refuses nothing reaches this plan
        _show_snapshot_plan(config, data_dir, console)  # AD-1341 S6: what a --full reset would keep
    return 0
```

**Pair 9, the archive commands' dispatch.** SEARCH:
```python
    if command == "veto":  # AD-1341 S3: the Captain's veto
        return _cmd_archive_veto(args)
```
REPLACE:
```python
    if command == "veto":  # AD-1341 S3: the Captain's veto
        return _cmd_archive_veto(args)
    if command == "snapshots":  # AD-1341 S6: the Ship's Records snapshots --full resets kept
        return _cmd_archive_snapshots(args)
    if command == "erase-snapshot":  # AD-1341 S6: the Captain's erasure of one
        return _cmd_archive_erase_snapshot(args)
```

**Pair 10, the two commands.** SEARCH:
```python
def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
    """Handle read-only git objects on Windows."""
```
REPLACE:
```python
def _cmd_archive_snapshots(args: argparse.Namespace) -> int:
    """``probos archive snapshots`` (AD-1341 S6): the Ship's Records snapshots ``--full`` resets kept.

    Each with its id, name, whether its file is there (``present``, ``missing``) or the Captain erased it, what it
    holds and the generation's dates. Reads the archive; records nothing. 0 shown; 1 the archive could not be read;
    2 the archive disabled. Plain ``print``: a name is shown as text, never as markup.
    """
    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): no snapshot is kept.")
        return 2
    try:
        entries = asyncio.run(_read_snapshot_entries(config))
    except Exception as exc:  # nothing is recorded either way; the Captain sees why
        print(f"The snapshots could not be read: {type(exc).__name__}: {exc}")
        return 1
    directory = _snapshots_dir(config)
    print(f"Ship's Records snapshots: {len(entries)}, in {directory}")
    for entry in entries:
        print(
            f"  {entry.id}: {entry.relative_path} {_snapshot_state(entry, directory)}; {entry.file_count} file(s), "
            f"{entry.total_bytes} bytes; generation {entry.generation_started} to {entry.generation_ended}"
        )
    if entries:
        print("Erase one: probos archive erase-snapshot SNAPSHOT_ID --reason TEXT.")
    return 0


def _snapshot_state(entry: SnapshotEntry, directory: Path) -> str:
    """What ``probos archive snapshots`` shows of one snapshot's file (AD-1341 S6)."""
    from probos.knowledge.records_snapshot import is_snapshot_relative_path

    if entry.erased_at is not None:  # AD-1341 S6 A4: an erasure that did not finish says so until it does
        if is_snapshot_relative_path(entry.relative_path) and os.path.lexists(directory / entry.relative_path):
            return "(erased by the Captain; its file remains: run probos archive erase-snapshot again)"
        return "(erased by the Captain)"
    if not is_snapshot_relative_path(entry.relative_path):
        return "(not a snapshot's name: never opened)"
    return "(present)" if (directory / entry.relative_path).is_file() else "(missing)"


async def _read_snapshot_entries(config: SystemConfig) -> tuple[SnapshotEntry, ...]:
    """Every recorded snapshot; the ledger is closed on every exit (AD-1341 S6)."""
    ledger = await _open_ledger(config)
    try:
        return await ledger.snapshot_entries()
    finally:
        await ledger.close()


def _cmd_archive_erase_snapshot(args: argparse.Namespace) -> int:
    """``probos archive erase-snapshot SNAPSHOT_ID --reason TEXT`` (AD-1341 S6): the Captain erases one snapshot.

    The ledger's row is marked erased first (the reason and the time; no content), then the file is deleted, so no
    snapshot is removed unrecorded. A deletion that fails is reported, and the same command finishes it. 0 erased,
    already erased or declined; 1 no such snapshot, a row that names no snapshot, or a failure; 2 the archive
    disabled, or a bad id or reason. Plain ``print``.
    """
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): there is no snapshot to erase.")
        return 2
    snapshot_id, reason = args.snapshot_id, args.reason
    if snapshot_id <= 0:
        print("A snapshot id is a positive integer, as probos archive snapshots lists it.")
        return 2
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        print(f"--reason needs 1 to {ARCHIVE_REASON_MAX_CHARS} characters.")
        return 2
    try:
        return asyncio.run(_erase_snapshot(config, snapshot_id, reason, bool(getattr(args, "yes", False))))
    except Exception as exc:  # the marker is one statement; the Captain sees why
        print(f"The erasure failed: {type(exc).__name__}: {exc}")
        return 1


async def _erase_snapshot(config: SystemConfig, snapshot_id: int, reason: str, confirmed: bool) -> int:
    """Show the snapshot, ask unless ``--yes``, mark it erased, then delete its file. The ledger is closed on every exit."""
    from probos.knowledge.records_snapshot import SnapshotRefused, is_snapshot_relative_path, retained_alias

    ledger = await _open_ledger(config)
    try:
        entry = await ledger.snapshot_by_id(snapshot_id)
        if entry is None:
            print(f"No Ship's Records snapshot has id {snapshot_id}.")
            return 1
        if not is_snapshot_relative_path(entry.relative_path):  # AD-1341 S6: a row never names a file outside the snapshots
            print(f"Snapshot {snapshot_id} names {entry.relative_path!r}, which is not a snapshot's name. Nothing was erased.")
            return 1
        problem = _snapshot_file_problem(_snapshots_dir(config), entry.relative_path)  # A2: before the marker
        if problem:
            print(f"Snapshot {snapshot_id}: {problem}. Nothing was erased.")
            return 1
        print(f"Ship's Records snapshot {entry.id}: {entry.relative_path} ({entry.file_count} file(s), timeline {entry.timeline_id})")
        if entry.erased_at is None:
            if not confirmed and input("  Erase it? Its file is deleted. [y/N]: ").strip().lower() != "y":
                print("Aborted. Nothing was erased.")
                return 0
            await ledger.mark_snapshot_erased(snapshot_id, reason)  # the marker first
    finally:
        await ledger.close()
    path = _snapshots_dir(config) / entry.relative_path
    try:
        alias = retained_alias(path)  # AD-1341 S6 A4 (A-R2-F2): the temporary name publish could not remove
        for name in (*([alias] if alias is not None else []), path):  # A4: the alias first, so a rerun still finds it
            name.unlink(missing_ok=True)
    except (OSError, SnapshotRefused) as exc:  # A5: a refusal here means the name changed after the check (R28)
        print(f"The erasure is recorded, but the file remains at {path}: {type(exc).__name__}: {exc}. Run the same command again.")
        return 1
    print(f"Erased Ship's Records snapshot {snapshot_id}: a marker keeps its name and the reason; its file is deleted.")
    return 0


def _snapshot_file_problem(directory: Path, relative_path: str) -> str:
    """AD-1341 S6 A2 (A-F3): why a recorded snapshot's path must not be erased, or ``""`` when it may. ``lstat`` only.

    Neither the snapshots directory nor the timeline's directory may be a link or junction, and what stands at the
    snapshot's own name, when anything does, must be a regular file: an erasure deletes only a snapshot inside the
    snapshots directory. Nothing there is fine (a ``missing`` row may still be marked). Any other ``OSError``
    propagates, and the erasure fails before its marker. A5 (A-R3-F1): a temporary name beside the snapshot whose
    identity cannot be shown (``retained_alias`` refuses: a file index of 0) is refused here too, before the marker.
    """
    import stat

    from probos.knowledge.records_snapshot import SnapshotRefused, is_link_or_junction, lstat_or_none, retained_alias

    path = directory / relative_path
    for component in (directory, path.parent):
        if is_link_or_junction(component):  # AD-1341 S6 A2: an erasure never follows one
            return f"{component} is a link or junction; an erasure deletes only inside the snapshots directory"
    status = lstat_or_none(path)
    if status is not None and not stat.S_ISREG(status.st_mode):  # a directory, a link or a special file there
        return f"{path} is not a snapshot's file"
    try:
        retained_alias(path)  # AD-1341 S6 A5 (A-R3-F1): a temporary name of unknown identity refuses before the marker
    except SnapshotRefused as exc:
        return str(exc)
    return ""


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
    """Handle read-only git objects on Windows."""
```

**Pair 11, the parser.** SEARCH:
```python
    archive_veto.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")

    args = parser.parse_args()
```
REPLACE:
```python
    archive_veto.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
    # AD-1341 S6: the Ship's Records snapshots --full resets kept beside the archive, and the Captain's erasure of one.
    archive_snapshots = archive_sub.add_parser(
        "snapshots", help="List the Ship's Records snapshots --full resets kept beside the Ship's Archive",
    )
    archive_snapshots.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    archive_erase_snapshot = archive_sub.add_parser(
        "erase-snapshot", help="Erase one Ship's Records snapshot: a marker records it, then its file is deleted",
    )
    archive_erase_snapshot.add_argument("snapshot_id", type=int, help="The snapshot's id, as snapshots lists it")
    archive_erase_snapshot.add_argument(
        "--reason", type=str, required=True, help="Why, in 1-500 characters; it is recorded.",
    )
    archive_erase_snapshot.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_erase_snapshot.add_argument(
        "--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",
    )

    args = parser.parse_args()
```

### 7.6 New file: `tests/test_ad1341_s6_records_snapshot.py` (M1)

```python
"""AD-1341 S6 (#1569), M1: a ``--full`` reset keeps what it deletes from Ship's Records as one checked snapshot.

Real objects throughout: the real ``_cmd_reset``, ``_cmd_archive`` and ``main`` on a temporary data directory, Ship's
Records written by the store's own producers, the real ``ArchiveStore`` and ``ArchiveLedger`` on a temporary archive
file, and the real ``OracleService``. The config loader is the one stand-in. No test reaches a real data directory:
the platform's data and home variables point under ``tmp_path`` and the CLI's default data directory raises (the
autouse fixture). A fault is injected only where the platform cannot produce one on demand: a sharing violation, a
file that changes between the listing and the copy, a member that reads back wrong, a ledger that refuses its row.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import struct
import sys
import types
import zipfile
import zlib
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import probos
from probos import __main__ as cli
from probos.knowledge import records_snapshot
from probos.cognitive.oracle_service import OracleService
from probos.config import ArchiveConfig, KnowledgeConfig, RecordsConfig, SystemConfig
from probos.knowledge.archive_ledger import ArchiveLedger, SnapshotRecord
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.records_snapshot import (
    SNAPSHOT_DIR_NAME,
    SnapshotPlan,
    SnapshotRefused,
    is_snapshot_relative_path,
    plan_snapshot,
    prepare_snapshot,
    snapshot_relative_path,
)
from probos.knowledge.records_store import RecordsStore
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_SHIP = "ship-did-alpha-0001"
_CONVERGENCE = "reports/convergence/convergence-20261022-000000.md"
_STARTED = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_ENDED = datetime(2026, 10, 27, 6, 0, 5, tzinfo=UTC)
_NAME = f"{_SHIP}/20261001T080000Z_20261027T060005Z.zip"
_DID = f"did:probos:{_SHIP}"


@pytest.fixture(autouse=True)
def _no_real_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every platform data and home path points under ``tmp_path``, and the CLI's default data directory raises."""
    home = tmp_path / "platform"
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(home / name.lower()))

    def _refuse() -> Path:
        raise AssertionError("AD-1341 S6: a test reached the platform data directory")

    monkeypatch.setattr(cli, "_default_data_dir", _refuse)


def _archive_db(tmp_path: Path) -> Path:
    return tmp_path / "archive" / "archive.db"


def _snapshots_dir(tmp_path: Path) -> Path:
    return tmp_path / "archive" / SNAPSHOT_DIR_NAME


def _config(tmp_path: Path, *, archive_enabled: bool = True) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=archive_enabled, db_path=str(_archive_db(tmp_path)))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _snapshot_files(tmp_path: Path) -> list[Path]:
    """Every file under the snapshots directory, a temporary ``.partial`` one included."""
    root = _snapshots_dir(tmp_path)
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


def _data_dir(tmp_path: Path, *, instance_id: str = _SHIP) -> Path:
    """A stopped vessel's data directory: one file of each tier, and the instance id written at ``_STARTED``."""
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    if instance_id:
        id_file = data_dir / "ontology" / "instance_id"
        id_file.write_text(f"{instance_id}\n", encoding="utf-8")
        os.utime(id_file, (_STARTED.timestamp(), _STARTED.timestamp()))  # the ship's first boot
    for name in ("events.db", "trust.db", "ward_room.db"):  # tiers 1, 2 and 3
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


async def _write_records(data_dir: Path) -> None:
    """A convergence report and the Captain's log (both promoted) and a private notebook (never promoted)."""
    writer = RecordsStore(RecordsConfig(repo_path=str(data_dir / "ship-records"), auto_commit=False))
    await writer.write_entry(
        author="system", path=_CONVERGENCE, content="## Convergence Report\n\nThree officers traced the coolant drift.",
        message="AD-551: Convergence report (coolant)", classification="ship", tags=["convergence"],
    )
    await writer.append_captains_log("Set course for the Briar Patch.")
    await writer.write_notebook(
        callsign="Chapel", topic_slug="private-coolant", content="A private note: tachyon residue in the coolant.",
        classification="private",
    )


def _files(root: Path, contents: dict[str, bytes]) -> None:
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _tree(root: Path, *, leave_out: tuple[str, ...] = ()) -> dict[str, bytes]:
    """Every regular file under ``root``: its POSIX path from ``root``, then its bytes; top-level ``leave_out`` skipped."""
    found: dict[str, bytes] = {}
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative.split("/")[0] in leave_out or not path.is_file():
            continue
        found[relative] = path.read_bytes()
    return found


def _data_files(data_dir: Path) -> dict[str, bytes]:
    """The data directory's files, without the takeover lock every executing reset leaves (S1 A4)."""
    return {path: content for path, content in _tree(data_dir).items() if path != "probos.pid.lock"}


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    """The real ``_cmd_reset`` with the loader returning ``config``; returns what it returns."""
    monkeypatch.setenv("COLUMNS", "200")  # Rich wraps at 80 columns off a terminal; the assertions read lines
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None,
    }
    values.update(flags)
    return cli._cmd_reset(Namespace(**values))


def _archive(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, command: str, **values: Any) -> Any:
    """The real ``_cmd_archive`` with the loader returning ``config``."""
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(Namespace(archive_cmd=command, config=None, **values))


def _erasures(tmp_path: Path) -> list[tuple[Any, ...]]:
    return _rows(_archive_db(tmp_path), "SELECT erased_at, erase_reason FROM archive_snapshots ORDER BY id")


def _link_dir(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere. A host that refuses skips."""
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this host cannot create a directory link: {exc}")


async def _later_crew_reads(tmp_path: Path, text: str) -> list[Any]:
    later = ArchiveStore(str(_archive_db(tmp_path)), connection_factory=default_factory)
    await later.initialize()
    try:
        oracle = OracleService(archive_store=later)
        oracle.attach_current_timeline("ship-did-beta-0002")
        return await oracle.query(text, tiers=["archive"])
    finally:
        await later.close()


def _prepare(root: Path, snapshots: Path, *, ended: datetime = _ENDED) -> Any:
    return prepare_snapshot(root, snapshots, timeline_id=_SHIP, ship_did=_DID, started=_STARTED, ended=ended)


# --- X1 to X5: the reset ------------------------------------------------------------------------------------------


def test_a_full_reset_keeps_ship_records_as_one_checked_bag_before_it_deletes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    records = data_dir / "ship-records"
    _files(records, {
        "notebooks/garbled.md": b"---\nauthor: Chapel\n---\n\xff\xfe not UTF-8",  # S1 register RA3-1
        ".git/HEAD": b"ref: refs/heads/main\n",
        "procedures/p-1.yaml": b"steps: STEP-BODY-SECRET\n",
    })
    kept = _tree(records, leave_out=(".git", "procedures"))
    assert "notebooks/garbled.md" in kept and any("private-coolant" in path for path in kept)  # premise

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 0

    out = capsys.readouterr().out
    assert _tree(records) == {}  # tier 3 deleted Ship's Records ...
    (snapshot,) = _snapshot_files(tmp_path)  # ... and kept them first, as one file
    relative = snapshot.relative_to(_snapshots_dir(tmp_path)).as_posix()
    assert relative.startswith(f"{_SHIP}/20261001T080000Z_") and is_snapshot_relative_path(relative)
    total = sum(len(content) for content in kept.values())
    assert _rows(
        _archive_db(tmp_path),
        "SELECT id, timeline_id, ship_did, generation_started, relative_path, sha256, file_count, total_bytes, "
        "erased_at FROM archive_snapshots",
    ) == [(
        1, _SHIP, _DID, "2026-10-01T08:00:00Z", relative, _sha256(snapshot.read_bytes()), len(kept), total, None,
    )]
    bag = Path(relative).stem
    with zipfile.ZipFile(snapshot) as bag_zip:
        prefix = f"{bag}/data/"
        payload = {name[len(prefix):]: bag_zip.read(name) for name in bag_zip.namelist() if name.startswith(prefix)}
        bagit = bag_zip.read(f"{bag}/bagit.txt")
        manifest = bag_zip.read(f"{bag}/manifest-sha256.txt").decode("utf-8")
        info = bag_zip.read(f"{bag}/bag-info.txt").decode("utf-8")
    assert payload == kept  # byte for byte, every classification, the undecodable file too; no .git, no procedures
    assert bagit == b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
    assert manifest.splitlines() == [f"{_sha256(content)}  data/{path}" for path, content in sorted(kept.items())]
    for line in (f"External-Identifier: {_DID}", f"ProbOS-Timeline: {_SHIP}", f"Payload-Oxum: {total}.{len(kept)}",
                 "ProbOS-Generation-Started: 2026-10-01T08:00:00Z"):
        assert f"{line}\n" in info
    assert "1 Markdown file(s) Ship's Records cannot list, never promoted, are kept in it: notebooks/garbled.md" in out
    assert _rows(_archive_db(tmp_path), "SELECT reset_tier, outcome FROM generations") == [(3, "promoted")]
    assert asyncio.run(_later_crew_reads(tmp_path, "tachyon")) == []  # a snapshot is no archive entry


def test_a_tier2_reset_keeps_ship_records_and_takes_no_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    before = _tree(data_dir / "ship-records")

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(0,)]
    assert _snapshot_files(tmp_path) == []
    assert _tree(data_dir / "ship-records") == before


_FAULTS = (
    "link", "too-many-files", "too-many-bytes", "grew", "shrank", "unreadable", "reads-back-wrong",
    "member-missing", "member-extra", "not-recorded",
)
#: A2: the faults the reset's preflight knows before anything is written: the archive is never even opened.
_PREFLIGHT_FAULTS = ("link", "too-many-files", "too-many-bytes")


def _inject(fault: str, records: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make one way a snapshot cannot be made happen."""
    real_plan, real_copy, real_text = (
        records_snapshot.plan_snapshot, records_snapshot._copy_member, records_snapshot._write_text,
    )
    if fault == "link":
        outside = tmp_path / "outside"
        _files(outside, {"secret.md": b"OUTSIDE-SECRET"})
        _link_dir(records / "linked", outside)
    elif fault == "too-many-files":
        monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 2)
    elif fault == "too-many-bytes":
        monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_BYTES", 10)
    elif fault in ("grew", "shrank"):
        def _listed_then_changed(root: Path) -> SnapshotPlan:
            plan = real_plan(root)
            target = root / _CONVERGENCE
            content = target.read_bytes()
            target.write_bytes(content + b"!" if fault == "grew" else content[:-1])
            return plan

        monkeypatch.setattr(records_snapshot, "plan_snapshot", _listed_then_changed)
    elif fault == "unreadable":
        def _sharing_violation(*args: Any, **kwargs: Any) -> str:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")

        monkeypatch.setattr(records_snapshot, "_copy_member", _sharing_violation)
    elif fault == "reads-back-wrong":
        def _wrong_digest(*args: Any, **kwargs: Any) -> str:
            real_copy(*args, **kwargs)
            return "0" * 64

        monkeypatch.setattr(records_snapshot, "_copy_member", _wrong_digest)
    elif fault == "member-missing":
        def _no_bag_info(bag_zip: Any, name: str, text: str, stamp: Any) -> None:
            if not name.endswith("/bag-info.txt"):
                real_text(bag_zip, name, text, stamp)

        monkeypatch.setattr(records_snapshot, "_write_text", _no_bag_info)
    elif fault == "member-extra":  # A3: a member the bag does not list; only the member-list check refuses it (P-8)
        def _one_more(bag_zip: Any, name: str, text: str, stamp: Any) -> None:
            real_text(bag_zip, name, text, stamp)
            if name.endswith("/bagit.txt"):  # after the last member the bag lists
                real_text(bag_zip, name.removesuffix("bagit.txt") + "unlisted.txt", "unlisted\n", stamp)

        monkeypatch.setattr(records_snapshot, "_write_text", _one_more)
    else:  # "not-recorded": the file is written and checked, then the ledger refuses its row
        async def _ledger_refuses(self: ArchiveLedger, snapshot: SnapshotRecord) -> int:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(ArchiveLedger, "record_snapshot", _ledger_refuses)


@pytest.mark.parametrize("fault", _FAULTS)
def test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing(
    fault: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    _inject(fault, data_dir / "ship-records", tmp_path, monkeypatch)
    changed = f"ship-records/{_CONVERGENCE}" if fault in ("grew", "shrank") else ""
    before = {path: content for path, content in _data_files(data_dir).items() if path != changed}

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1

    after = _data_files(data_dir)
    assert set(after) == set(before) | ({changed} if changed else set())  # Ship's Records and every tier file
    assert {path: content for path, content in after.items() if path != changed} == before
    assert _snapshot_files(tmp_path) == []  # no snapshot, and no temporary file left behind
    if fault in _PREFLIGHT_FAULTS:  # A2: refused before anything is written: no promotion, description or row
        assert not _archive_db(tmp_path).exists()
    else:
        assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(0,)]
        assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]  # closed only with its snapshot
    assert not (data_dir / "probos.pid").exists()


def test_skip_promotion_skips_the_snapshot_with_it_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, skip_promotion="drill") == 0

    assert "The Ship's Records snapshot is skipped with it." in capsys.readouterr().out
    assert _snapshot_files(tmp_path) == []
    assert _rows(_archive_db(tmp_path), "SELECT reset_tier, outcome, reason FROM generations") == [(3, "skipped", "drill")]
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(0,)]


def test_without_an_instance_id_a_full_reset_of_ship_records_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path, instance_id="")
    _files(data_dir / "ship-records", {"manuals/m.md": b"---\nauthor: shipyard\n---\nA manual, never a source.\n"})
    before = _data_files(data_dir)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1
    assert _data_files(data_dir) == before

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0  # tier 2 keeps Ship's Records: S1's rule, unchanged
    assert (data_dir / "ship-records" / "manuals" / "m.md").is_file()


# --- X6 to X10: the plan, the bag, the name ------------------------------------------------------------------------


def test_the_plan_lists_every_file_but_git_and_procedures_within_its_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "records"
    _files(root, {
        "a.md": b"a", "notebooks/b.md": b"bb", "notebooks/procedures/c.md": b"ccc", "reports/.hidden": b"x",
        ".git/HEAD": b"head", "procedures/p.yaml": b"steps",
    })
    plan = plan_snapshot(root)
    assert [(item.path, item.size) for item in plan.files] == [
        ("a.md", 1), ("notebooks/b.md", 2), ("notebooks/procedures/c.md", 3), ("reports/.hidden", 1),
    ]  # only the top-level .git and procedures stay out
    assert plan.total_bytes == 7
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 4)
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_BYTES", 7)
    assert len(plan_snapshot(root).files) == 4  # exactly at both bounds
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 3)
    with pytest.raises(SnapshotRefused, match="bound"):
        plan_snapshot(root)
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 4)
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_BYTES", 6)
    with pytest.raises(SnapshotRefused, match="bound"):
        plan_snapshot(root)
    assert plan_snapshot(tmp_path / "absent") == SnapshotPlan(files=(), total_bytes=0)
    (tmp_path / "empty").mkdir()
    assert _prepare(tmp_path / "empty", tmp_path / "snaps") is None
    assert not (tmp_path / "snaps").exists()  # an empty tree writes nothing
    (tmp_path / "a-file").write_bytes(b"x")
    with pytest.raises(SnapshotRefused, match="not a directory"):
        plan_snapshot(tmp_path / "a-file")


def test_a_link_inside_ship_records_is_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "records"
    _files(root, {"notebooks/a.md": b"a"})
    outside = tmp_path / "outside"
    _files(outside, {"secret.md": b"OUTSIDE"})
    _link_dir(root / "notebooks" / "linked", outside)

    with pytest.raises(SnapshotRefused, match="notebooks/linked is a link"):
        plan_snapshot(root)


def test_a_prepared_snapshot_reads_back_as_written_and_is_published_once(tmp_path: Path) -> None:
    root = tmp_path / "records"
    _files(root, {"100%.md": b"percent", "notes/a b.md": b"space"})

    prepared = _prepare(root, tmp_path / "snaps")

    assert prepared.result.relative_path == _NAME
    assert (prepared.result.file_count, prepared.result.total_bytes) == (2, 12)
    assert prepared.result.paths == ("100%.md", "notes/a b.md")
    assert prepared.temp_path.is_file() and not prepared.final_path.exists()  # checked, not yet in place
    assert prepared.result.sha256 == _sha256(prepared.temp_path.read_bytes())
    prepared.publish()
    assert prepared.final_path == tmp_path / "snaps" / _NAME
    assert prepared.final_path.is_file() and not prepared.temp_path.exists()
    bag = "20261001T080000Z_20261027T060005Z"
    with zipfile.ZipFile(prepared.final_path) as bag_zip:
        assert bag_zip.namelist() == [
            f"{bag}/data/100%.md", f"{bag}/data/notes/a b.md", f"{bag}/manifest-sha256.txt", f"{bag}/bag-info.txt",
            f"{bag}/bagit.txt",
        ]
        manifest = bag_zip.read(f"{bag}/manifest-sha256.txt").decode("utf-8")
        info = bag_zip.read(f"{bag}/bag-info.txt").decode("utf-8")
    assert manifest == f"{_sha256(b'percent')}  data/100%25.md\n{_sha256(b'space')}  data/notes/a b.md\n"
    for line in ("Bagging-Date: 2026-10-27", "Payload-Oxum: 12.2", f"External-Identifier: {_DID}",
                 "ProbOS-Generation-Started: 2026-10-01T08:00:00Z", "ProbOS-Generation-Ended: 2026-10-27T06:00:05Z",
                 "ProbOS-Excluded: .git/ procedures/"):
        assert f"{line}\n" in info


def test_a_snapshot_is_never_written_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    first = _prepare(root, tmp_path / "snaps")
    first.publish()
    published = first.final_path.read_bytes()

    with pytest.raises(SnapshotRefused, match="exists already"):
        _prepare(root, tmp_path / "snaps")  # the same name: refused before anything is written
    assert first.final_path.read_bytes() == published

    later = _prepare(root, tmp_path / "snaps", ended=_ENDED.replace(second=6))
    later.final_path.write_bytes(b"someone else's file")  # appears after the check, before publishing
    with pytest.raises(SnapshotRefused, match="exists already"):
        later.publish()
    assert later.final_path.read_bytes() == b"someone else's file"
    later.discard()
    assert not later.temp_path.exists()

    racing = _prepare(root, tmp_path / "snaps", ended=_ENDED.replace(second=7))
    with monkeypatch.context() as patch:  # A2 (A-F4): the name appears after any check publish could make
        patch.setattr(records_snapshot.os.path, "lexists", lambda _path: False)
        racing.final_path.write_bytes(b"a racing writer's file")
        with pytest.raises(SnapshotRefused, match="exists already"):
            racing.publish()
    assert racing.final_path.read_bytes() == b"a racing writer's file"
    racing.discard()


@pytest.mark.parametrize("timeline", ["", " ", "../ship", "ship/one", "ship one", "a" * 65, ".hidden", "ship\n", None])
def test_an_instance_id_that_cannot_name_a_directory_refuses_the_snapshot(timeline: Any) -> None:
    with pytest.raises(SnapshotRefused):
        snapshot_relative_path(timeline, _STARTED, _ENDED)


def test_only_a_snapshot_s_own_name_is_a_snapshot_path() -> None:
    assert snapshot_relative_path(_SHIP, _STARTED, _ENDED) == _NAME
    assert snapshot_relative_path("a" * 64, _STARTED, _ENDED).startswith("a" * 64 + "/")
    assert is_snapshot_relative_path(_NAME)
    for bad in (f"../{_NAME}", f"{_SHIP}/../../escape.zip", f"{_SHIP}/notes.zip", _NAME + "/../x",
                _NAME.replace("/", "\\"), "", None, 7):
        assert not is_snapshot_relative_path(bad)
    with pytest.raises(ValueError):
        snapshot_relative_path(_SHIP, datetime(2026, 10, 1, 8, 0), _ENDED)  # a time with no offset


# --- X11 to X14: the ledger, the Captain's commands, the census, the dry run ---------------------------------------


def _record(**changes: Any) -> SnapshotRecord:
    record = SnapshotRecord(
        timeline_id=_SHIP, ship_did=_DID, generation_started="2026-10-01T08:00:00Z",
        generation_ended="2026-10-27T06:00:05Z", relative_path=_NAME, sha256="a" * 64, file_count=3, total_bytes=99,
    )
    return dataclasses.replace(record, **changes) if changes else record


async def test_the_ledger_records_a_snapshot_without_its_content_and_marks_its_erasure_once(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    store = ArchiveStore(str(path), connection_factory=default_factory)
    await store.initialize()  # the store owns the schema: it creates archive_snapshots
    await store.close()
    ledger = ArchiveLedger(str(path), connection_factory=default_factory)
    await ledger.initialize()
    try:
        first = await ledger.record_snapshot(_record())
        with pytest.raises(sqlite3.IntegrityError):
            await ledger.record_snapshot(_record())  # one row per file name
        (entry,) = await ledger.snapshot_entries()
        assert (entry.id, entry.relative_path, entry.erased_at, entry.erase_reason) == (first, _NAME, None, "")
        marked = await ledger.mark_snapshot_erased(first, "the Captain's order")
        again = await ledger.mark_snapshot_erased(first, "a second reason")
        assert marked is not None and again is not None and marked.erased_at is not None
        assert (again.erased_at, again.erase_reason) == (marked.erased_at, "the Captain's order")  # the first stands
        assert await ledger.snapshot_by_id(first) == again
        assert await ledger.snapshot_by_id(first + 1) is None
        assert await ledger.mark_snapshot_erased(first + 1, "x") is None
        assert await ledger.mark_snapshot_erased(2**63, "x") is None
        for bad_id in (0, -1):
            with pytest.raises(ValueError):
                await ledger.mark_snapshot_erased(bad_id, "x")
        for reason in ("", "  ", "x" * 501):
            with pytest.raises(ValueError):
                await ledger.mark_snapshot_erased(first, reason)
    finally:
        await ledger.close()
    assert [row[1] for row in _rows(path, "PRAGMA table_info(archive_snapshots)")] == [
        "id", "timeline_id", "ship_did", "generation_started", "generation_ended", "relative_path", "sha256",
        "file_count", "total_bytes", "recorded_at", "erased_at", "erase_reason",
    ]  # no column for content
    for change in ({"sha256": "A" * 64}, {"sha256": "a" * 63}, {"file_count": -1}, {"total_bytes": True},
                   {"relative_path": " "}, {"ship_did": ""}):
        with pytest.raises(ValueError):
            _record(**change)


async def test_the_ledger_opens_only_an_archive_the_store_has_brought_to_its_schema(tmp_path: Path) -> None:
    for name, version in (("v7.db", 7), ("v0.db", 0)):
        connection = sqlite3.connect(str(tmp_path / name))
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
        connection.close()
        ledger = ArchiveLedger(str(tmp_path / name), connection_factory=default_factory)
        with pytest.raises(RuntimeError, match=f"schema version {version}"):
            await ledger.initialize()


def test_the_captain_lists_and_erases_a_snapshot_with_the_marker_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    relative = snapshot.relative_to(_snapshots_dir(tmp_path)).as_posix()
    capsys.readouterr()

    assert _archive(monkeypatch, config, "snapshots") == 0
    assert f"  1: {relative} (present);" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=False) == 0
    assert snapshot.is_file() and _erasures(tmp_path) == [(None, "")]  # declined: nothing recorded or deleted

    real_unlink = Path.unlink

    def _locked(self: Path, missing_ok: bool = False) -> None:
        if self == snapshot:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _locked)
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="the Captain's order", yes=True) == 1
    assert snapshot.is_file()  # the file remains ...
    ((erased_at, reason),) = _erasures(tmp_path)
    assert erased_at is not None and reason == "the Captain's order"  # ... and the marker came first
    monkeypatch.setattr(Path, "unlink", real_unlink)

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="again", yes=True) == 0
    assert not snapshot.exists()  # the same command finished it
    assert _erasures(tmp_path) == [(erased_at, "the Captain's order")]  # the first reason stands
    capsys.readouterr()
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert f"  1: {relative} (erased by the Captain);" in capsys.readouterr().out
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=2, reason="x", yes=True) == 1  # no such id


def test_an_erasure_never_deletes_a_file_outside_the_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    outside = tmp_path / "archive" / "escape.zip"
    outside.write_bytes(b"not a snapshot")
    connection = sqlite3.connect(str(_archive_db(tmp_path)))
    connection.execute("UPDATE archive_snapshots SET relative_path = ?", ("../escape.zip",))  # a hand-edited row
    connection.commit()
    connection.close()

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 1

    assert outside.read_bytes() == b"not a snapshot" and snapshot.is_file()
    assert _erasures(tmp_path) == [(None, "")]
    disabled = _config(tmp_path, archive_enabled=False)
    assert _archive(monkeypatch, disabled, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 2
    assert _archive(monkeypatch, disabled, "snapshots") == 2
    for bad_id, bad_reason in ((0, "x"), (1, " "), (1, "x" * 501)):
        assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=bad_id, reason=bad_reason, yes=True) == 2


@pytest.mark.parametrize(
    ("argv", "attribute", "value"),
    [
        (["archive", "snapshots"], "archive_cmd", "snapshots"),
        (["archive", "erase-snapshot", "3", "--reason", "drill", "--yes"], "snapshot_id", 3),
    ],
    ids=["snapshots", "erase-snapshot"],
)
def test_main_parses_the_snapshot_commands(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], attribute: str, value: Any,
) -> None:
    seen: list[Namespace] = []

    def _command(args: Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, "_cmd_archive", _command)
    monkeypatch.setattr("sys.argv", ["probos", *argv])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [getattr(args, attribute) for args in seen] == [value]


def test_only_the_cli_records_or_erases_a_snapshot_and_nothing_else_reads_one() -> None:
    """``record_snapshot`` and ``mark_snapshot_erased`` are named in ``src`` by ``__main__.py`` alone, and only it
    imports ``records_snapshot``: no agent, service or Oracle tier writes or reads a snapshot."""
    naming: dict[str, set[str]] = {"record_snapshot": set(), "mark_snapshot_erased": set()}
    importing: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative = path.relative_to(_SRC).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in naming:
                naming[node.attr].add(relative)
            elif isinstance(node, ast.Constant) and type(node.value) is str and node.value in naming:
                naming[node.value].add(relative)
            elif isinstance(node, ast.ImportFrom) and (
                node.module == "probos.knowledge.records_snapshot"
                or (node.module == "probos.knowledge" and any(alias.name == "records_snapshot" for alias in node.names))
            ):
                importing.add(relative)
    assert naming == {"record_snapshot": {"__main__.py"}, "mark_snapshot_erased": {"__main__.py"}}
    assert importing == {"__main__.py"}


def test_a_dry_run_shows_the_snapshot_a_full_reset_would_keep_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    records = data_dir / "ship-records"
    files = len(plan_snapshot(records).files)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, dry_run=True) == 0
    assert f"Ship's Records snapshot: {files} file(s)" in capsys.readouterr().out
    assert not _snapshots_dir(tmp_path).exists()

    outside = tmp_path / "outside"
    _files(outside, {"secret.md": b"OUTSIDE"})
    _link_dir(records / "linked", outside)
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, dry_run=True) == 0
    assert "The Ship's Records snapshot would refuse this reset" in capsys.readouterr().out


# --- A2: the round-1 repairs ---------------------------------------------------------------------------------------


def test_a_publish_that_fails_leaves_its_row_shown_missing_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (A-F7): the row is recorded before the file is published, so a publish that fails leaves the row, never
    deleted, which ``probos archive snapshots`` shows as missing; the reset refuses with nothing deleted."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    before = _data_files(data_dir)
    config = _config(tmp_path)

    def _no_space(self: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(records_snapshot.PreparedSnapshot, "publish", _no_space)

    assert _reset(monkeypatch, config, data_dir, full=True) == 1

    assert _data_files(data_dir) == before and _snapshot_files(tmp_path) == []
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(1,)]  # the row stays
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]
    capsys.readouterr()
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert "(missing);" in capsys.readouterr().out


def test_a_ship_records_root_that_cannot_be_inspected_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F1): only a root that is not there is an empty plan; an error inspecting it propagates."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    real_lstat = os.lstat

    def _denied(path: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(path, (str, os.PathLike)) and Path(path) == root:
            raise PermissionError(13, "Access is denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(records_snapshot.os, "lstat", _denied)
    with pytest.raises(PermissionError):
        plan_snapshot(root)


def test_a_ship_records_root_that_is_a_link_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F1): a root that is a link or junction refuses, in the plan and in the reset, before anything is written."""
    outside = tmp_path / "outside"
    _files(outside, {"notebooks/a.md": b"OUTSIDE"})
    _link_dir(tmp_path / "records-link", outside)
    with pytest.raises(SnapshotRefused, match="is a link"):
        plan_snapshot(tmp_path / "records-link")

    data_dir = _data_dir(tmp_path)
    _link_dir(data_dir / "ship-records", outside)
    before = _tree(outside)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1

    assert _tree(outside) == before and (data_dir / "trust.db").is_file()
    assert not _archive_db(tmp_path).exists()  # refused before anything was written


def test_a_tag_file_that_reads_back_wrong_refuses_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F6): the read-back reads the tag files whole too, so zipfile checks their CRCs."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    real_verify = records_snapshot._verify_bag

    def _manifest_damaged(temp: Path, bag: str, plan: SnapshotPlan, digests: dict[str, str]) -> str:
        with zipfile.ZipFile(temp) as bag_zip:
            member = bag_zip.getinfo(f"{bag}/manifest-sha256.txt")
        with open(temp, "r+b") as raw:
            raw.seek(member.header_offset + 26)
            name_length, extra_length = struct.unpack("<HH", raw.read(4))
            raw.seek(member.header_offset + 30 + name_length + extra_length + member.compress_size // 2)
            (byte,) = raw.read(1)
            raw.seek(-1, os.SEEK_CUR)
            raw.write(bytes([byte ^ 0xFF]))
        return real_verify(temp, bag, plan, digests)

    monkeypatch.setattr(records_snapshot, "_verify_bag", _manifest_damaged)
    with pytest.raises((zipfile.BadZipFile, zlib.error, EOFError)):
        _prepare(root, tmp_path / "snaps")
    assert [path for path in (tmp_path / "snaps").rglob("*") if path.is_file()] == []  # the temporary file is removed


def test_a_file_system_without_hard_links_refuses_to_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F4): publication is a hard link, never a rename that may replace; where links fail, it refuses."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    prepared = _prepare(root, tmp_path / "snaps")

    def _unsupported(*args: Any, **kwargs: Any) -> None:
        raise OSError(95, "Operation not supported")

    monkeypatch.setattr(records_snapshot.os, "link", _unsupported)
    with pytest.raises(SnapshotRefused, match="hard link"):
        prepared.publish()
    assert not prepared.final_path.exists() and prepared.temp_path.is_file()  # kept for the caller's discard
    prepared.discard()
    assert not prepared.temp_path.exists()


def test_an_erasure_deletes_only_a_regular_file_inside_the_snapshots_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F3): before its marker, the erasure refuses a directory at the snapshot's name and a timeline directory
    that is a link or junction; nothing is marked or deleted."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    snapshot.unlink()
    snapshot.mkdir()  # a directory where the snapshot's file was
    (snapshot / "keep.txt").write_bytes(b"keep")

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 1
    assert (snapshot / "keep.txt").read_bytes() == b"keep" and _erasures(tmp_path) == [(None, "")]

    shutil.rmtree(snapshot.parent)
    outside = tmp_path / "outside"
    _files(outside, {snapshot.name: b"OUTSIDE"})
    _link_dir(snapshot.parent, outside)  # the timeline's directory leads out of the snapshots directory

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 1
    assert (outside / snapshot.name).read_bytes() == b"OUTSIDE" and _erasures(tmp_path) == [(None, "")]


def test_a_dry_run_says_a_full_reset_without_an_instance_id_would_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (A-F5): the dry run and the reset share one preflight; no snapshot is promised that the reset would refuse."""
    data_dir = _data_dir(tmp_path, instance_id="")
    _files(data_dir / "ship-records", {"manuals/m.md": b"---\nauthor: shipyard\n---\nA manual, never a source.\n"})

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "This reset would refuse" in out
    assert "Institutional Knowledge" not in out  # A4 (R2-B1): a refused dry run shows no tier table, reads nothing more
    assert "No instance id: Ship's Records hold 1 file(s)" in out
    assert "would be kept" not in out
    assert not _archive_db(tmp_path).exists()


def test_a_snapshot_is_written_only_into_the_snapshots_directory_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (A-F2): a link or junction at the snapshots directory or the timeline's refuses the snapshot, in
    ``prepare_snapshot`` and in the reset's preflight; at every tier the snapshots directory, resolved, may not be
    inside or around what the reset deletes."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _link_dir(tmp_path / "snaps", elsewhere)
    with pytest.raises(SnapshotRefused, match="is a link"):
        _prepare(root, tmp_path / "snaps")
    assert list(elsewhere.rglob("*")) == []

    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    before = _data_files(data_dir)
    _snapshots_dir(tmp_path).mkdir()
    _link_dir(_snapshots_dir(tmp_path) / _SHIP, data_dir / "ship-records" / "reports")  # into what --full deletes

    assert _reset(monkeypatch, config, data_dir, full=True) == 1

    assert _data_files(data_dir) == before
    assert not _archive_db(tmp_path).exists()  # the preflight refused before anything was written

    base = tmp_path / "tier2"
    data2 = _data_dir(base)
    config2 = _config(base)
    _files(data2 / "semantic", {"older.zip": b"an older snapshot"})
    _link_dir(_snapshots_dir(base), data2 / "semantic")  # the snapshots directory is what tier 2 deletes
    capsys.readouterr()

    assert _reset(monkeypatch, config2, data2) == 1

    assert (data2 / "semantic" / "older.zip").read_bytes() == b"an older snapshot"
    assert "the Ship's Archive is inside what this reset deletes" in capsys.readouterr().out


# --- A4: the round-2 repairs ---------------------------------------------------------------------------------------


def _posix_stat() -> Any:
    """A POSIX build's ``stat`` module, stricter: no ``IO_REPARSE_TAG_*`` (Windows-only) and no ``FILE_ATTRIBUTE_*``.

    A5: ``Lib/stat.py`` defines the 17 ``FILE_ATTRIBUTE_*`` constants on every platform; they are removed here too,
    and no S6 module reads either set (X18's scan), so no result depends on the difference (A4).
    Swapped in for ``records_snapshot.stat`` only, never deleted from the interpreter's ``stat``: the standard library
    reads those names itself on Windows (``ntpath.isjunction``)."""
    return types.SimpleNamespace(**{
        name: value for name, value in vars(stat).items()
        if not name.startswith(("_", "IO_REPARSE_TAG_", "FILE_ATTRIBUTE_"))
    })


def test_an_erasure_removes_the_temporary_name_a_publish_could_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A4 (A-R2-F2): a temporary name ``publish`` could not remove after its link is the snapshot's own file under a
    second name. The erasure removes it first, then the snapshot; while either remains it exits 1 and the listing says
    the file remains; the same command finishes it. The denial is injected: POSIX has no sharing violation."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    real_unlink = Path.unlink
    denied: list[Path] = []

    def _shared(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(".partial") and len(denied) < 2:  # the publish's removal, then the erasure's first
            denied.append(self)
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _shared)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    snapshot, alias = sorted(_snapshot_files(tmp_path), key=lambda path: path.name.startswith("."))
    assert alias.name == f".{snapshot.name}.partial"
    assert os.path.samestat(os.lstat(snapshot), os.lstat(alias))  # premise: one file, two names
    relative = snapshot.relative_to(_snapshots_dir(tmp_path)).as_posix()
    capsys.readouterr()

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 1
    assert snapshot.is_file() and alias.is_file()  # the alias first: the final name is still there to find it by
    assert "Run the same command again" in capsys.readouterr().out
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert (
        f"  1: {relative} (erased by the Captain; its file remains: run probos archive erase-snapshot again);"
        in capsys.readouterr().out
    )

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="again", yes=True) == 0
    assert _snapshot_files(tmp_path) == [] and len(denied) == 2
    assert _erasures(tmp_path)[0][1] == "drill"  # the first reason stands
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert f"  1: {relative} (erased by the Captain);" in capsys.readouterr().out


def test_an_erasure_leaves_a_temporary_name_that_is_another_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4 (A-R2-F2): only the snapshot's own file is removed under its temporary name; another file there (another
    attempt's, or a copy with the same bytes) is never touched. Identity decides, not the name or the content."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    other = snapshot.with_name(f".{snapshot.name}.partial")
    other.write_bytes(snapshot.read_bytes())  # the same bytes, another file
    assert not os.path.samestat(os.lstat(snapshot), os.lstat(other))  # premise

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 0

    assert _snapshot_files(tmp_path) == [other] and other.read_bytes()[:2] == b"PK"


def test_an_erasure_refuses_a_temporary_name_whose_identity_cannot_be_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A5 (A-R3-F1): ``os.path.samestat`` compares ``st_dev`` and ``st_ino``, and an index of 0 identifies no file.
    With every index reported as 0, another file at the temporary name refuses the erasure before its marker: exit 1,
    both names and the row unchanged. Once the Captain removes it, the same command erases: a zero index with no
    temporary name beside the snapshot is unaffected. Injected at the module's status boundary: no file system is
    known to report 0 where a hard link succeeds (R48). On ``77b65917`` the first erasure removed the other file."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    other = records_snapshot.temporary_name(snapshot)
    other.write_bytes(b"another attempt's file")
    assert not os.path.samestat(os.lstat(snapshot), os.lstat(other))  # premise: two files, real indices differ
    real_lstat = records_snapshot.lstat_or_none

    def _no_file_index(path: Path) -> Any:
        status = real_lstat(path)
        if status is None:
            return None
        return types.SimpleNamespace(
            st_mode=status.st_mode, st_dev=status.st_dev, st_ino=0,
            st_reparse_tag=getattr(status, "st_reparse_tag", 0),
        )

    monkeypatch.setattr(records_snapshot, "lstat_or_none", _no_file_index)
    capsys.readouterr()

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 1
    out = capsys.readouterr().out
    assert "cannot be shown" in out and "Nothing was erased." in out
    assert _snapshot_files(tmp_path) == sorted([snapshot, other])
    assert other.read_bytes() == b"another attempt's file"
    assert _erasures(tmp_path) == [(None, "")]  # refused before the marker

    other.unlink()  # the Captain, having checked it
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="again", yes=True) == 0
    assert _snapshot_files(tmp_path) == [] and _erasures(tmp_path)[0][1] == "again"


def test_a_status_is_judged_by_its_mode_and_only_a_junction_s_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4 (A-R2-F1): ``is_link_status`` names nothing a POSIX build's ``stat`` lacks. A POSIX status (no
    ``st_reparse_tag``) is judged by its mode; a Windows status is a link by its mode or a junction's tag, and any
    other reparse tag (a cloud placeholder) is not a link. No S6 module names a Windows-only ``stat`` attribute."""
    monkeypatch.setattr(records_snapshot, "stat", _posix_stat())
    status = types.SimpleNamespace

    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFDIR | 0o755)) is False
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFREG | 0o644)) is False
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFLNK | 0o777)) is True
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFDIR, st_reparse_tag=0xA0000003)) is True  # junction
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFREG, st_reparse_tag=0x9000001A)) is False  # cloud
    for relative in (
        "knowledge/records_snapshot.py", "knowledge/archive_ledger.py", "knowledge/nature_description.py", "__main__.py",
    ):
        path = _SRC / relative
        if relative == "knowledge/nature_description.py" and not path.exists():  # M2's file: absent on M1's tree only
            continue
        text = path.read_text(encoding="utf-8-sig")
        assert re.search(r"\bstat\.(IO_REPARSE_TAG_|FILE_ATTRIBUTE_)|\bst_file_attributes\b", text) is None, relative


@pytest.mark.parametrize("command", ["full", "dry-run", "erasure"])
def test_a_full_reset_its_dry_run_and_an_erasure_need_no_windows_only_name(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4 (A-R2-F1): the real commands, with ``records_snapshot`` seeing a POSIX build's ``stat``, finish as they do
    on Windows (on ``2a1b6319`` each raised ``AttributeError``; the erasure reported it and exited 1)."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    if command == "erasure":
        assert _reset(monkeypatch, config, data_dir, full=True) == 0  # premise, with the platform's own stat
    monkeypatch.setattr(records_snapshot, "stat", _posix_stat())

    if command == "erasure":
        assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 0
        assert _snapshot_files(tmp_path) == [] and _erasures(tmp_path)[0][1] == "drill"
    else:
        assert _reset(monkeypatch, config, data_dir, full=True, dry_run=command == "dry-run") == 0
        assert len(_snapshot_files(tmp_path)) == (1 if command == "full" else 0)
        assert (data_dir / "trust.db").exists() is (command == "dry-run")
```

The first S6 import is `from probos.knowledge import records_snapshot` (placed before `probos.cognitive`, so it is the import that fails on M1's base; keep that order even if a formatter would sort it).

### 7.7 `src/probos/knowledge/archive_store.py` (M2)

The closed set gains the description. **This SEARCH anchors on S5's line** (S5 anchors, after §11). SEARCH:
```python
    AFTER_ACTION_REPORT = "after_action"  # AD-1341 S5: a lesson after a flagged event, endorsed by the chain; cites episodes
```
REPLACE:
```python
    AFTER_ACTION_REPORT = "after_action"  # AD-1341 S5: a lesson after a flagged event, endorsed by the chain; cites episodes
    NATURE_DESCRIPTION = "nature_description"  # AD-1341 S6: which procedures a crew developed and why; never a procedure
```

### 7.8 `src/probos/knowledge/archive_promotion.py` (M2)

The description's one writer, so S1's census (only this module names `promote_entry`) holds. No new import: the module's `probos` imports stay `archive_store`, `lessons` and `records_store` (`tests/test_ad1341_s1_promotion.py:413-423`). The SEARCH is S3's text, which S5 does not touch on this tree. SEARCH:
```python
        vetoed=tuple(vetoed),
    )


@dataclass(frozen=True)
class PendingSource:
```
REPLACE:
```python
        vetoed=tuple(vetoed),
    )


#: AD-1341 S6: a nature description's source reference, ``nature-description/{timeline_id}``: one per crew generation.
NATURE_DESCRIPTION_PREFIX = "nature-description/"


async def promote_nature_description(archive: ArchiveStore, record: PromotionRecord) -> PromotionOutcome:
    """AD-1341 S6: archive one generation's nature description (``probos.knowledge.nature_description`` builds it).

    The Captain's amendment of 2026-10-16: procedures and skills persist as nature and are never promoted; the archive
    gets a description of what a crew developed and why. Only a ``NATURE_DESCRIPTION`` record with its
    ``nature-description/`` reference and no source episodes is accepted. ``promote_entry`` then applies the
    idempotence key and the Captain's erasure markers and vetoes, as for every source. A2 (B-F2): one per generation:
    once an entry is archived for the reference, with any content, a later description is PRESENT and nothing is
    written (``_nature_state``); other kinds keep S1's revisions.
    """
    if (
        type(record) is not PromotionRecord
        or record.source_kind is not SourceKind.NATURE_DESCRIPTION
        or not record.source_ref.startswith(NATURE_DESCRIPTION_PREFIX)
        or record.source_episode_ids
    ):
        raise ValueError("AD-1341 S6: only a nature description, citing no episode, is promoted here")
    if (await _nature_state(archive, record)).outcome is PromotionOutcome.PRESENT:
        outcome = PromotionOutcome.PRESENT  # A2 (B-F2): this generation's description is archived already
    else:
        outcome = await archive.promote_entry(record)
    logger.info("AD-1341 S6: nature description %s: %s", record.source_ref, outcome.value)
    return outcome


async def review_nature_description(archive: ArchiveStore, record: PromotionRecord) -> PendingSource:
    """AD-1341 S6: what promoting this generation's nature description now would do. Reads; records nothing.

    The review service's read of the archive (``source_state``), as ``review_promotion`` is for Ship's Records, so
    ``probos archive pending`` shows the description as the reset would treat it, and ``source_state`` stays named in
    ``src`` by this module alone (``tests/test_ad1341_s3_veto_store.py``).
    """
    return PendingSource(record, await _nature_state(archive, record))


async def _nature_state(archive: ArchiveStore, record: PromotionRecord) -> SourceState:
    """AD-1341 S6 A2 (B-F2): what promoting a nature description would do. One per generation: an entry archived for
    its reference, with any content, makes a later one PRESENT, never a revision; the first is kept."""
    state = await archive.source_state(record)
    if state.outcome is PromotionOutcome.CREATED and state.entry_ids:  # A2 (B-F2): one per generation
        return SourceState(PromotionOutcome.PRESENT, state.entry_ids)
    return state


@dataclass(frozen=True)
class PendingSource:
```

### 7.9 New file: `src/probos/knowledge/nature_description.py` (M2)

```python
"""AD-1341 S6 (#1569): the nature description, culture's record of the nature a crew generation leaves behind.

The Captain's amendment of 2026-10-16 (nature, culture and nurture): proven Cognitive JIT procedures and skills persist
across a reset as nature, a crew's own ability that is never narrated as inherited, and they are not promoted into the
Ship's Archive. The archive gets a *description* instead: which procedures this generation developed and why. The
procedure itself (its steps, ``content_snapshot``) stays in its store and never enters the archive.

- The facts are the procedure store's own: name, description, evolution type, whether it is active, retired or an
  anti-pattern, its selection, completion and fallback counts, and an evolved procedure's change summary. They are
  read read-only from ``procedures/procedures.db``, from columns every version of its table has. No model is called.
  Each text is folded to one line, stripped of control and format characters, and cut to a bound.
- "Developed by this generation" means created at or after ``started``: the reset passes the modification time of
  ``ontology/instance_id``, which the ontology loader writes once, at the ship's first boot.
- Skills are not described: the skill catalog (``config/skills``) is part of the installation and outside every reset,
  and it does not keep which crew forged a skill (each boot registers a skill file again as ``internal``).
- The whole entry fits one Oracle tool entry (``NATURE_DESCRIPTION_MAX_CHARS``); procedures beyond it are counted, not
  listed. The entry names no agent: lineage stays in the store (the amendment's item 2).
  ``archive_promotion.promote_nature_description`` is its one writer.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.knowledge.archive_promotion import NATURE_DESCRIPTION_PREFIX
from probos.knowledge.archive_store import PromotionRecord, SourceKind
from probos.knowledge.lessons import EXIT_NOTE_TIMELINE_MAX_CHARS

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

#: Where the procedure store keeps its index, under the data directory (``runtime.py``: ``data_dir / "procedures"``).
PROCEDURES_DB = Path("procedures") / "procedures.db"

#: The description's text at most: with its title, S2's longest label and the tool's marker it stays inside one Oracle
#: tool entry (``oracle_query_tool._MAX_ENTRY_CHARS``, 1,200), as S4's lessons do.
NATURE_DESCRIPTION_MAX_CHARS = 900
NATURE_NAME_MAX_CHARS = 60
NATURE_TEXT_MAX_CHARS = 120
#: At most this many procedures are read to be listed (a read bound; the text budget usually binds first).
NATURE_LISTED_MAX = 10

_MORE_RESERVE = 48  # room for "And N more in the procedure store."

_DEVELOPED_COUNT_SQL = "SELECT COUNT(*) FROM procedure_records WHERE created_at >= ?"
_DEVELOPED_SQL = (
    "SELECT name, description, evolution_type, is_active, is_negative, total_selections, total_completions, "
    "total_fallbacks, change_summary FROM procedure_records "
    "WHERE created_at >= ? ORDER BY total_completions DESC, created_at, id LIMIT ?"
)
_ACTIVE_SQL = "SELECT COUNT(*) FROM procedure_records WHERE is_active = 1 AND is_negative = 0"


def _one_line(value: object, limit: int) -> str:
    """One line of printable text of at most ``limit`` characters: control and format characters become spaces."""
    if type(value) is not str:
        return ""
    printable = "".join(" " if unicodedata.category(char)[0] == "C" else char for char in value)
    text = " ".join(printable.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


@dataclass(frozen=True)
class ProcedureFact:
    """What the description may say about one procedure: never its steps."""

    name: str
    description: str
    evolution: str
    state: str  # "active", "retired" or "an anti-pattern"
    selections: int
    completions: int
    fallbacks: int
    change_summary: str = ""

    @classmethod
    def from_row(cls, row: Any) -> ProcedureFact:
        name, description, evolution, active, negative, selections, completions, fallbacks, summary = row
        state = "an anti-pattern" if negative else ("active" if active else "retired")
        return cls(
            name=_one_line(name, NATURE_NAME_MAX_CHARS) or "(unnamed)",
            description=_one_line(description, NATURE_TEXT_MAX_CHARS),
            evolution=_one_line(evolution, 16).lower() or "captured",
            state=state,
            selections=_count(selections),
            completions=_count(completions),
            fallbacks=_count(fallbacks),
            change_summary=_one_line(summary, NATURE_TEXT_MAX_CHARS),
        )


def _fact_line(fact: ProcedureFact) -> str:
    line = (
        f"- {fact.name}: {fact.description or '(no description)'} ({fact.evolution}, {fact.state}; "
        f"{fact.completions} of {fact.selections} uses completed, {fact.fallbacks} fell back)"
    )
    return f"{line}; changed because: {fact.change_summary}" if fact.change_summary else line


def describe_nature(
    timeline_id: str, started: datetime, facts: tuple[ProcedureFact, ...], *, developed: int, active: int,
) -> PromotionRecord:
    """The nature description entry: a header, one line per procedure that fits, and a count of the rest."""
    if type(timeline_id) is not str or not timeline_id.strip() or len(timeline_id) > EXIT_NOTE_TIMELINE_MAX_CHARS:
        raise ValueError(f"AD-1341 S6: a timeline of 1..{EXIT_NOTE_TIMELINE_MAX_CHARS} characters is required")
    since = started.astimezone(UTC).strftime("%Y-%m-%d")
    lines = [
        f"Procedures this crew developed since {since} (UTC, the ship's first boot): {developed}; "
        f"{active} active in the store at the close.",
        "They stay in the procedure store as nature. This records what they are and why, never their steps.",
    ]
    budget = NATURE_DESCRIPTION_MAX_CHARS - _MORE_RESERVE
    listed = 0
    for fact in facts:
        line = _fact_line(fact)
        if len("\n".join(lines)) + 1 + len(line) > budget:
            break
        lines.append(line)
        listed += 1
    if developed > listed:
        lines.append(f"And {developed - listed} more in the procedure store.")
    return PromotionRecord(
        timeline_id=timeline_id,
        source_kind=SourceKind.NATURE_DESCRIPTION,
        source_ref=f"{NATURE_DESCRIPTION_PREFIX}{timeline_id}",
        title=f"Procedures developed by the crew of timeline {timeline_id}",
        content="\n".join(lines),
        classification="ship",
        metadata={
            "procedures_developed": developed,
            "procedures_active_at_close": active,
            "procedures_listed": listed,
            "generation_started": started.astimezone(UTC).isoformat(),
        },
    )


async def nature_description_record(
    db_path: Path,
    open_read_only: Callable[[str], Awaitable[DatabaseConnection]],
    *,
    timeline_id: str,
    started: datetime,
) -> PromotionRecord | None:
    """The description of the procedures created since ``started``, or None when there is nothing to describe.

    None with no procedure store, or when no procedure was created since ``started``. The store is opened through
    ``open_read_only`` (the CLI passes SQLite's ``mode=ro``), so a missing file is never created and the database's
    own bytes never change. A2 (B-F4): the vessel's store is in WAL mode (``procedure_store.py:211``), and a reader may
    create or touch its ``-wal`` and ``-shm`` files (``storage/sqlite_factory.py:28-31``). Any database error
    propagates, and the reset refuses.
    """
    if not db_path.is_file():  # no procedure store: this generation developed nothing to describe
        return None
    since = started.timestamp()
    db = await open_read_only(str(db_path))
    try:
        cursor = await db.execute(_DEVELOPED_COUNT_SQL, (since,))
        developed = int((await cursor.fetchone())[0])
        if developed == 0:
            return None
        cursor = await db.execute(_DEVELOPED_SQL, (since, NATURE_LISTED_MAX))
        rows = await cursor.fetchall()
        cursor = await db.execute(_ACTIVE_SQL)
        active = int((await cursor.fetchone())[0])
    finally:
        await db.close()
    facts = tuple(ProcedureFact.from_row(row) for row in rows)
    return describe_nature(timeline_id, started, facts, developed=developed, active=active)
```

### 7.10 `src/probos/__main__.py` (M2)

Nine pairs, in file order; pair 1 and pair 2 anchor on M1's text (A2 rewrote pairs 1, 2, 6 and 7 and added pair 9).

**Pair 1, the description at tiers 2 and 3: read before the snapshot, archived after it (A2, B-F2).** SEARCH:
```python
        notes: list[str] = []
        if tier >= 3:  # AD-1341 S6: what a --full reset deletes from Ship's Records is kept first, as one checked file
            notes.append(await _snapshot_ship_records(config, data_dir, timeline_id))
```
REPLACE:
```python
        nature = await _nature_record(data_dir, timeline_id)  # AD-1341 S6 A2: read before the snapshot
        notes: list[str] = []
        if tier >= 3:  # AD-1341 S6: what a --full reset deletes from Ship's Records is kept first, as one checked file
            notes.append(await _snapshot_ship_records(config, data_dir, timeline_id))
        notes.insert(0, await _describe_nature(archive, nature))  # AD-1341 S6 A2: archived after the snapshot (B-F2)
```

**Pair 2, the description's helpers.** SEARCH:
```python
#: AD-1341 S6: the Ship's Records directory a tier 3 reset deletes (``RESET_TIERS[3]["dirs"]``), so the one it keeps.
```
REPLACE:
```python
async def _open_read_only(path: str) -> DatabaseConnection:
    """AD-1341 S6: open a database the reset only reads, through SQLite's ``mode=ro`` (BF-906): never created."""
    from probos.storage.sqlite_factory import default_factory

    return await default_factory.connect(path, read_only=True)


async def _nature_record(data_dir: Path, timeline_id: str) -> PromotionRecord | None:
    """AD-1341 S6: this generation's nature description, built one way for the reset, the dry run, pending and veto."""
    from probos.knowledge.nature_description import PROCEDURES_DB, nature_description_record

    started = _generation_started(data_dir)
    if started is None or not timeline_id:
        return None
    return await nature_description_record(
        data_dir / PROCEDURES_DB, _open_read_only, timeline_id=timeline_id, started=started,
    )


async def _describe_nature(archive: ArchiveStore, record: PromotionRecord | None) -> str:
    """AD-1341 S6: archive this generation's nature description before the reset; say what became of it.

    A2 (B-F2): the promotion reads ``record`` before the snapshot (an unreadable store refuses there) and archives it
    here, after the snapshot, so a snapshot that fails leaves no description to duplicate on the retry.
    """
    from probos.knowledge.archive_promotion import promote_nature_description

    if record is None:
        return "Nature description: this generation developed no Cognitive JIT procedure, so there is none."
    outcome = await promote_nature_description(archive, record)
    return f"Nature description {record.source_ref}: {outcome.value}."


async def _pending_nature(config: SystemConfig, data_dir: Path) -> PendingSource | None:
    """AD-1341 S6: the nature description the next reset would archive, with what promoting it now would do."""
    from probos.knowledge.archive_promotion import review_nature_description

    record = await _nature_record(data_dir, _read_instance_id(data_dir))
    if record is None:
        return None
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        return await review_nature_description(archive, record)  # S3's census: only archive_promotion names source_state
    finally:
        await archive.close()


#: AD-1341 S6: the Ship's Records directory a tier 3 reset deletes (``RESET_TIERS[3]["dirs"]``), so the one it keeps.
```

**Pair 3, the dry run builds it.** SEARCH:
```python
        plan = asyncio.run(
            plan_promotion(_reset_records_store(config, data_dir), timeline_id=timeline_id or _UNATTRIBUTED_TIMELINE)
        )
    except Exception as exc:  # the dry run reports it; nothing is touched either way
```
REPLACE:
```python
        plan = asyncio.run(
            plan_promotion(_reset_records_store(config, data_dir), timeline_id=timeline_id or _UNATTRIBUTED_TIMELINE)
        )
        nature = asyncio.run(_nature_record(data_dir, timeline_id))  # AD-1341 S6: the description the reset would archive
    except Exception as exc:  # the dry run reports it; nothing is touched either way
```

**Pair 4, the dry run shows it whole.** SEARCH:
```python
    for path in plan.withheld:
        console.print(f"    - withheld: {escape(path)}")
```
REPLACE:
```python
    for path in plan.withheld:
        console.print(f"    - withheld: {escape(path)}")
    if nature is not None:  # AD-1341 S6: the Captain reads what a later crew would
        console.print(f"    + {escape(nature.source_ref)} (the nature description):")
        for line in nature.content.splitlines():
            console.print(f"      {escape(line)}")
```

**Pair 5, `pending` reads it.** SEARCH:
```python
        review = asyncio.run(_review_pending_promotion(config, data_dir, timeline_id))
    except Exception as exc:  # nothing is recorded either way; the Captain sees why
```
REPLACE:
```python
        review = asyncio.run(_review_pending_promotion(config, data_dir, timeline_id))
        nature = asyncio.run(_pending_nature(config, data_dir))  # AD-1341 S6: this generation's nature description
    except Exception as exc:  # nothing is recorded either way; the Captain sees why
```

**Pair 6, `pending` lists it.** SEARCH:
```python
    for pending in review.sources:
        print(f"  {_pending_label(pending.state)}: {pending.record.source_ref}")
    for path in review.withheld:
        print(f"  - withheld: {path}")
    if review.sources:
```
REPLACE:
```python
    for pending in review.sources:
        print(f"  {_pending_label(pending.state)}: {pending.record.source_ref}")
    if nature is not None:  # AD-1341 S6: the next reset would archive it too; probos archive veto keeps it out
        print(f"  {_pending_label(nature.state)}: {nature.record.source_ref} (the nature description):")
        print(f"    {nature.record.title}")
        for line in nature.record.content.splitlines():  # AD-1341 S6 A2 (B-F1): the Captain reads the text itself
            print(f"    {line}")
    for path in review.withheld:
        print(f"  - withheld: {path}")
    if review.sources or nature is not None:
```

**Pair 7, `veto`'s imports.** SEARCH:
```python
    from probos.knowledge.archive_promotion import plan_promotion
    from probos.knowledge.archive_store import VetoOutcome
```
REPLACE:
```python
    from probos.knowledge.archive_promotion import NATURE_DESCRIPTION_PREFIX, plan_promotion
    from probos.knowledge.archive_store import SourceKind, VetoOutcome
```

**Pair 8, `veto` accepts it.** SEARCH:
```python
    record = next((item for item in plan.records if item.source_ref == source_ref), None)
    if record is None:
```
REPLACE:
```python
    record = next((item for item in plan.records if item.source_ref == source_ref), None)
    if record is None and source_ref.startswith(NATURE_DESCRIPTION_PREFIX):  # AD-1341 S6: this generation's description
        nature = await _nature_record(data_dir, timeline_id)
        record = nature if nature is not None and nature.source_ref == source_ref else None
    if record is None:
```

**Pair 9, the veto's confirmation shows the description's text (A2, B-F1).** SEARCH (S3's text):
```python
    print(f"Ship's Records source {record.source_ref}: {record.title}")
    print(f"  kind: {record.source_kind.value}")
```
REPLACE:
```python
    print(f"Ship's Records source {record.source_ref}: {record.title}")
    print(f"  kind: {record.source_kind.value}")
    if record.source_kind is SourceKind.NATURE_DESCRIPTION:  # AD-1341 S6 A2 (B-F1): the text it keeps out
        for line in record.content.splitlines():
            print(f"    {line}")
```

### 7.11 `tests/test_ad1341_s1_archive_store.py` (M2)

**This SEARCH anchors on S5's text.** SEARCH:
```python
    # AD-1341 S5: so does the after-action report, a lesson after an event the Captain flagged, endorsed by the chain of
    # command; it too cites episodes by id and is not one.
    assert {kind.value for kind in SourceKind} == {
        "convergence_report", "published_report", "captains_log", "notebook_finding", "exit_note", "after_action",
    }
```
REPLACE:
```python
    # AD-1341 S5: so does the after-action report, a lesson after an event the Captain flagged, endorsed by the chain of
    # command; it too cites episodes by id and is not one.
    # AD-1341 S6: so does the nature description, which says which procedures a crew developed and why; it cites no
    # episode and holds no procedure.
    assert {kind.value for kind in SourceKind} == {
        "convergence_report", "published_report", "captains_log", "notebook_finding", "exit_note", "after_action",
        "nature_description",
    }
```

### 7.12 New file: `tests/test_ad1341_s6_nature_description.py` (M2)

```python
"""AD-1341 S6 (#1569), M2: every tier 2 and 3 reset archives a description of the procedures the crew developed,
never the procedures.

Real objects: the real ``_cmd_reset`` and ``_cmd_archive`` on a temporary data directory; a ``procedures.db`` built
with the procedure store's own schema (``procedure_store._SCHEMA``); the real ``ArchiveStore``, ``OracleService`` and
Oracle tool. The config loader is the one stand-in. No test reaches a real data directory (the autouse fixture).
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sqlite3
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from probos import __main__ as cli
from probos.knowledge import records_snapshot
from probos.knowledge.archive_promotion import (
    NATURE_DESCRIPTION_PREFIX,
    promote_nature_description,
    review_nature_description,
)
from probos.cognitive.oracle_service import OracleService
from probos.cognitive.procedure_store import _SCHEMA as _PROCEDURE_SCHEMA
from probos.config import ArchiveConfig, KnowledgeConfig, SystemConfig
from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome, SourceKind, SourceState
from probos.knowledge.nature_description import (
    NATURE_DESCRIPTION_MAX_CHARS,
    PROCEDURES_DB,
    _one_line,
    describe_nature,
    nature_description_record,
)
from probos.storage.sqlite_factory import default_factory
from probos.tools.oracle_query_tool import _MAX_ENTRY_CHARS, OracleQueryTool

_SHIP = "ship-did-alpha-0001"
_NEXT_SHIP = "ship-did-beta-0002"
_BOOT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_B = _BOOT.timestamp()
_INHERITED = {
    "id": "p-0", "name": "Inherited routine", "description": "From an earlier crew.", "created_at": _B - 86400.0,
    "total_selections": 50, "total_completions": 50,
}
_ROWS = (
    _INHERITED,
    {"id": "p-1", "name": "Coolant drift triage", "description": "Trace a coolant drift to its sensor before purging.",
     "created_at": _B + 60.0, "total_selections": 9, "total_completions": 8, "total_fallbacks": 1,
     "content_snapshot": '{"steps": ["STEP-BODY-SECRET"]}'},
    {"id": "p-2", "name": "Coolant drift triage, sensor first", "description": "Check the sensor, then trace the drift.",
     "evolution_type": "FIX", "change_summary": "The sensor check now comes first.", "created_at": _B + 120.0,
     "total_selections": 3, "total_completions": 3},
    {"id": "p-3", "name": "Purge before isolating", "description": "Purging before isolating vents the core.",
     "is_negative": 1, "created_at": _B + 30.0, "total_selections": 2, "total_fallbacks": 2},
)
_EXPECTED = "\n".join((
    "Procedures this crew developed since 2026-10-01 (UTC, the ship's first boot): 3; 3 active in the store at the "
    "close.",
    "They stay in the procedure store as nature. This records what they are and why, never their steps.",
    "- Coolant drift triage: Trace a coolant drift to its sensor before purging. (captured, active; 8 of 9 uses "
    "completed, 1 fell back)",
    "- Coolant drift triage, sensor first: Check the sensor, then trace the drift. (fix, active; 3 of 3 uses "
    "completed, 0 fell back); changed because: The sensor check now comes first.",
    "- Purge before isolating: Purging before isolating vents the core. (captured, an anti-pattern; 0 of 2 uses "
    "completed, 2 fell back)",
))
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:59s]"


@pytest.fixture(autouse=True)
def _no_real_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every platform data and home path points under ``tmp_path``, and the CLI's default data directory raises."""
    home = tmp_path / "platform"
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(home / name.lower()))

    def _refuse() -> Path:
        raise AssertionError("AD-1341 S6: a test reached the platform data directory")

    monkeypatch.setattr(cli, "_default_data_dir", _refuse)


def _archive_db(tmp_path: Path) -> Path:
    return tmp_path / "archive" / "archive.db"


def _config(tmp_path: Path) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=True, db_path=str(_archive_db(tmp_path)))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _data_dir(tmp_path: Path, *, instance_id: str = _SHIP) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    if instance_id:
        id_file = data_dir / "ontology" / "instance_id"
        id_file.write_text(f"{instance_id}\n", encoding="utf-8")
        os.utime(id_file, (_B, _B))  # the ship's first boot
    for name in ("events.db", "trust.db", "ward_room.db"):
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


def _procedure_store(data_dir: Path, rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> Path:
    """``procedures/procedures.db`` with the store's own schema and ``rows``."""
    path = data_dir / PROCEDURES_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_PROCEDURE_SCHEMA)
        for row in rows:
            columns, marks = ", ".join(row), ", ".join("?" for _ in row)
            connection.execute(f"INSERT INTO procedure_records ({columns}) VALUES ({marks})", tuple(row.values()))
        connection.commit()
    finally:
        connection.close()
    return path


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None,
    }
    values.update(flags)
    return cli._cmd_reset(Namespace(**values))


def _archive(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, command: str, **values: Any) -> Any:
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(Namespace(archive_cmd=command, config=None, **values))


async def _read_only(path: str) -> Any:
    return await default_factory.connect(path, read_only=True)


async def _later_crew_reads(tmp_path: Path, text: str) -> list[Any]:
    later = ArchiveStore(str(_archive_db(tmp_path)), connection_factory=default_factory)
    await later.initialize()
    try:
        oracle = OracleService(archive_store=later)
        oracle.attach_current_timeline(_NEXT_SHIP)
        return await oracle.query(text, tiers=["archive"])
    finally:
        await later.close()


def test_a_reset_archives_one_description_of_what_this_crew_developed_never_the_procedures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    created = _rows(store, "SELECT id FROM procedure_records WHERE created_at >= ? ORDER BY created_at, id", (_B,))
    assert created == [("p-3",), ("p-1",), ("p-2",)]  # premise: not the completions order _EXPECTED lists
    before = store.read_bytes()

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    archive = _archive_db(tmp_path)
    assert _rows(
        archive,
        "SELECT timeline_id, source_kind, source_ref, title, classification, author_did, author_callsign, "
        "source_episode_ids FROM archive",
    ) == [(
        _SHIP, "nature_description", f"{NATURE_DESCRIPTION_PREFIX}{_SHIP}",
        f"Procedures developed by the crew of timeline {_SHIP}", "ship", "", "", "[]",
    )]
    ((content,),) = _rows(archive, "SELECT content FROM archive")
    assert content == _EXPECTED  # developed since the first boot only, listed by completions; never a step
    assert "STEP-BODY-SECRET" not in content and "Inherited routine" not in content
    assert store.read_bytes() == before  # read, never written; nature persists at tier 2
    assert f"Nature description {NATURE_DESCRIPTION_PREFIX}{_SHIP}: created." in capsys.readouterr().out
    assert _rows(archive, "SELECT timeline_id, reset_tier, outcome, created_count FROM generations") == [
        (_SHIP, 2, "promoted", 0),
    ]  # the generation's counts stay Ship's Records' own
    results = asyncio.run(_later_crew_reads(tmp_path, "sensor"))
    assert [result.content.splitlines()[0] for result in results] == [
        "[Inherited from the crew of generation 1: not your own memory]",
    ]


@pytest.mark.parametrize("shape", ["long-text", "short-text"])
async def test_a_description_at_its_bound_reaches_a_later_crew_whole_through_the_oracle_tool(
    shape: str, tmp_path: Path,
) -> None:
    timeline = "t" * 64
    long_text = shape == "long-text"
    rows = [
        {"id": f"p-{index:02d}", "created_at": _B + index, "evolution_type": "FIX" if long_text else "CAPTURED",
         "name": "N" * 100 if long_text else f"P{index:02d}",
         "description": f"NATUREBOUND {'D' * 300}" if long_text else "NATUREBOUND",
         "change_summary": "S" * 300 if long_text else ""}
        for index in range(40)
    ]
    store = _procedure_store(_data_dir(tmp_path, instance_id=timeline), rows)

    record = await nature_description_record(store, _read_only, timeline_id=timeline, started=_BOOT)

    assert record is not None and len(record.content) <= NATURE_DESCRIPTION_MAX_CHARS
    listed = record.metadata["procedures_listed"]
    assert 1 <= listed < 40 and record.content.count("\n- ") == listed
    assert record.content.endswith(f"And {40 - listed} more in the procedure store.")
    archive = ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await archive.initialize()
    try:
        assert await promote_nature_description(archive, record) is PromotionOutcome.CREATED
        oracle = OracleService(archive_store=archive)
        oracle.attach_current_timeline(_NEXT_SHIP)
        result = await OracleQueryTool(oracle=oracle).invoke({"query": "NATUREBOUND", "kind": "archive"})
    finally:
        await archive.close()
    assert not result.error and result.metadata["returned_count"] == 1  # premise: the real tool delivered it
    entry = result.output[result.output.index("[source:archive"):].rstrip("\n")
    marker, label = entry.splitlines()[:2]
    assert label.startswith("[Inherited from ") and "[entry shortened]" not in entry
    for line in record.content.splitlines():
        assert line in entry  # whole: the count of the rest too
    assert len(entry) - len(marker) - len(label) + len(_WORST_MARKER) + len(_WORST_LABEL) <= _MAX_ENTRY_CHARS


@pytest.mark.parametrize("case", ["no-store", "nothing-since-boot", "no-instance-id"])
def test_nothing_to_describe_archives_nothing_and_creates_no_store(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path, instance_id="" if case == "no-instance-id" else _SHIP)
    if case == "nothing-since-boot":
        _procedure_store(data_dir, [_INHERITED])
    elif case == "no-instance-id":
        _procedure_store(data_dir, _ROWS)

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    archive = _archive_db(tmp_path)
    if archive.exists():
        assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_kind = 'nature_description'") == [(0,)]
    if case == "no-store":
        assert not (data_dir / "procedures").exists()  # a read-only open never creates the store


@pytest.mark.parametrize(
    ("raw", "limit", "expected"),
    [
        ("a\nb\tc", 20, "a b c"),
        ("\x1b[31mred\x1b[0m", 20, "[31mred [0m"),
        ("bidi‮evil", 20, "bidi evil"),
        ("zero​width", 20, "zero width"),
        ("  spaced   out  ", 20, "spaced out"),
        ("x" * 30, 10, "xxxxxxx..."),
        (None, 20, ""),
    ],
    ids=["whitespace", "escape", "bidi-override", "zero-width", "spaces", "cut", "not-text"],
)
def test_text_from_the_store_is_one_line_without_control_or_format_characters(
    raw: Any, limit: int, expected: str,
) -> None:
    assert _one_line(raw, limit) == expected


def test_the_captain_reviews_and_vetoes_a_description_before_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    config = _config(tmp_path)
    ref = f"{NATURE_DESCRIPTION_PREFIX}{_SHIP}"

    assert _archive(monkeypatch, config, "pending", data_dir=data_dir) == 0
    out = capsys.readouterr().out
    assert f"  + would be promoted: {ref}" in out
    assert f"    Procedures developed by the crew of timeline {_SHIP}" in out
    for line in _EXPECTED.splitlines():  # A2 (B-F1): the Captain reviews the text itself, whole
        assert f"    {line}" in out

    connection = sqlite3.connect(str(store))  # the store changes after the review: the reset's text differs
    connection.execute(
        "INSERT INTO procedure_records (id, name, created_at) VALUES (?, ?, ?)", ("p-9", "Late arrival", _B + 999.0),
    )
    connection.commit()
    connection.close()
    assert _archive(
        monkeypatch, config, "veto", data_dir=data_dir, source_ref=ref, reason="not this one", yes=True,
    ) == 0
    assert "Late arrival" in capsys.readouterr().out  # A2 (B-F1): the veto shows the text it keeps out

    assert _reset(monkeypatch, config, data_dir) == 0

    assert f"Nature description {ref}: vetoed." in capsys.readouterr().out
    archive = _archive_db(tmp_path)
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_kind = 'nature_description'") == [(0,)]
    assert _rows(archive, "SELECT source_kind, source_ref, reason FROM archive_vetoes") == [
        ("nature_description", ref, "not this one"),
    ]


def test_a_procedure_store_that_cannot_be_read_refuses_the_reset_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    (data_dir / PROCEDURES_DB).parent.mkdir(parents=True)
    (data_dir / PROCEDURES_DB).write_bytes(b"not a database " * 100)

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 1

    assert "DatabaseError" in capsys.readouterr().out
    assert all((data_dir / name).is_file() for name in ("events.db", "trust.db", "ward_room.db"))
    assert (data_dir / "ontology" / "instance_id").is_file()


async def test_only_a_nature_description_without_episodes_is_promoted_as_one(tmp_path: Path) -> None:
    good = describe_nature(_SHIP, _BOOT, (), developed=1, active=0)
    archive = ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await archive.initialize()
    try:
        for bad in (
            dataclasses.replace(good, source_kind=SourceKind.CONVERGENCE_REPORT),
            dataclasses.replace(good, source_episode_ids=("ep-1",)),
            dataclasses.replace(good, source_ref="reports/elsewhere.md"),
        ):
            with pytest.raises(ValueError):
                await promote_nature_description(archive, bad)
        assert await archive.count() == 0
        assert await promote_nature_description(archive, good) is PromotionOutcome.CREATED
        assert await promote_nature_description(archive, good) is PromotionOutcome.PRESENT  # once per content
    finally:
        await archive.close()
    with pytest.raises(ValueError):
        describe_nature("t" * 65, _BOOT, (), developed=1, active=0)


def test_the_dry_run_shows_the_description_the_reset_would_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _procedure_store(data_dir, _ROWS)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert f"    + {NATURE_DESCRIPTION_PREFIX}{_SHIP} (the nature description):" in out
    for line in _EXPECTED.splitlines():
        assert f"      {line}" in out
    assert not _archive_db(tmp_path).exists()  # a dry run opens no archive


def test_a_retried_reset_keeps_one_description_per_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (B-F2): a reset refused after its description was archived, retried after the store changed, archives no
    second description of the same generation; the review says it is archived already."""
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    config = _config(tmp_path)
    ref = f"{NATURE_DESCRIPTION_PREFIX}{_SHIP}"
    real_close = ArchiveStore.record_generation
    attempts: list[Any] = []

    async def _locked_once(self: ArchiveStore, closure: Any) -> Any:
        attempts.append(closure)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("database is locked")
        return await real_close(self, closure)

    monkeypatch.setattr(ArchiveStore, "record_generation", _locked_once)

    assert _reset(monkeypatch, config, data_dir) == 1  # refused after the description was archived
    archive = _archive_db(tmp_path)
    descriptions = "SELECT content FROM archive WHERE source_kind = 'nature_description'"
    assert _rows(archive, descriptions) == [(_EXPECTED,)]
    assert (data_dir / "ontology" / "instance_id").is_file()

    connection = sqlite3.connect(str(store))  # the vessel ran again before the retry: the store changed
    connection.execute(
        "INSERT INTO procedure_records (id, name, created_at) VALUES (?, ?, ?)", ("p-9", "Late arrival", _B + 999.0),
    )
    connection.commit()
    connection.close()
    capsys.readouterr()
    assert _archive(monkeypatch, config, "pending", data_dir=data_dir) == 0
    assert f"  = already archived (entry 1): {ref}" in capsys.readouterr().out

    assert _reset(monkeypatch, config, data_dir) == 0

    assert f"Nature description {ref}: present." in capsys.readouterr().out
    assert _rows(archive, descriptions) == [(_EXPECTED,)]  # one per generation: the first is kept
    assert _rows(archive, "SELECT COUNT(*) FROM generations") == [(1,)]


async def test_one_description_per_generation_whatever_its_content(tmp_path: Path) -> None:
    """A2 (B-F2): once a generation's description is archived, a later one for the same reference is ``present``,
    never a revision, in the writer and in the review alike."""
    first = describe_nature(_SHIP, _BOOT, (), developed=1, active=0)
    later = describe_nature(_SHIP, _BOOT, (), developed=2, active=1)
    assert first.source_ref == later.source_ref and first.content != later.content  # premise
    archive = ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await archive.initialize()
    try:
        assert await promote_nature_description(archive, first) is PromotionOutcome.CREATED
        assert await promote_nature_description(archive, later) is PromotionOutcome.PRESENT
        assert await archive.count() == 1
        review = await review_nature_description(archive, later)
        assert review.state == SourceState(PromotionOutcome.PRESENT, (1,))
    finally:
        await archive.close()


def test_a_full_reset_whose_snapshot_fails_archives_no_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (B-F2): the description is archived after the snapshot, so a snapshot that fails leaves none behind."""
    data_dir = _data_dir(tmp_path)
    _procedure_store(data_dir, _ROWS)
    notebooks = data_dir / "ship-records" / "notebooks"
    notebooks.mkdir(parents=True)
    (notebooks / "a.md").write_bytes(b"a note")

    def _sharing_violation(*args: Any, **kwargs: Any) -> str:
        raise PermissionError(13, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(records_snapshot, "_copy_member", _sharing_violation)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1

    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive WHERE source_kind = 'nature_description'") == [
        (0,),
    ]
    assert (notebooks / "a.md").read_bytes() == b"a note"


def test_a_wal_mode_store_is_described_and_its_database_bytes_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (B-F4): the vessel's store is in WAL mode (``procedure_store.py:211``). Read through ``mode=ro``, its
    database bytes are unchanged; SQLite may create the ``-wal`` and ``-shm`` files beside it, as any reader may."""
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    connection = sqlite3.connect(str(store))
    connection.execute("PRAGMA journal_mode=WAL")
    connection.close()
    assert _rows(store, "PRAGMA journal_mode") == [("wal",)]  # premise
    before = store.read_bytes()

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    for line in _EXPECTED.splitlines():
        assert f"      {line}" in out
    assert store.read_bytes() == before
```

The first S6 import is `from probos.knowledge.archive_promotion import NATURE_DESCRIPTION_PREFIX, ...` (placed before `probos.cognitive`; keep that order).

### 7.13 `src/probos/knowledge/archive_store.py` (M3)

Anchors on M1's text (7.3).

**Pair 1, the docstring.** SEARCH:
```python
archive. Its rows are written by ``probos.knowledge.archive_ledger``, on a
connection of its own, never by this class.
```
REPLACE:
```python
archive. Its rows are written by ``probos.knowledge.archive_ledger``, on a
connection of its own, never by this class. So are those of
``nature_clearances``, the content-free marker of each ``--clean-slate``.
```

**Pair 2, the schema.** SEARCH:
```python
CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_snapshots_path ON archive_snapshots(relative_path);
"""
```
REPLACE:
```python
CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_snapshots_path ON archive_snapshots(relative_path);

CREATE TABLE IF NOT EXISTS nature_clearances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    reset_tier INTEGER NOT NULL,
    cleared TEXT NOT NULL DEFAULT '[]',
    procedure_count INTEGER NOT NULL,
    cleared_at REAL NOT NULL
);
"""
```

### 7.14 `docs/development/store-baseline.yaml` (M3)

SEARCH (M1's text):
```yaml
  - archive_snapshots
  - archive_vetoes
  - generations
```
REPLACE:
```yaml
  - archive_snapshots
  - archive_vetoes
  - generations
  - nature_clearances
```

### 7.15 `src/probos/knowledge/archive_ledger.py` (M3)

Four pairs on M1's text.

**Pair 1, the docstring.** SEARCH:
```python
SHA-256, its file count and size (``probos.knowledge.records_snapshot`` writes the file beside the archive).
```
REPLACE:
```python
SHA-256, its file count and size (``probos.knowledge.records_snapshot`` writes the file beside the archive).
``nature_clearances`` (M3) holds no content either: each ``--clean-slate``, its timeline and tier, what it cleared and
how many procedures the store held, recorded before anything is deleted (``record_nature_clearance``, reached only
from ``probos reset``).
```

**Pair 2, the statement.** SEARCH:
```python
_SNAPSHOT_ERASE_SQL = (
    "UPDATE archive_snapshots SET erased_at = ?, erase_reason = ? WHERE id = ? AND erased_at IS NULL"
)
```
REPLACE:
```python
_SNAPSHOT_ERASE_SQL = (
    "UPDATE archive_snapshots SET erased_at = ?, erase_reason = ? WHERE id = ? AND erased_at IS NULL"
)
_NATURE_CLEARANCE_SQL = (
    "INSERT INTO nature_clearances (timeline_id, reset_tier, cleared, procedure_count, cleared_at) "
    "VALUES (?, ?, ?, ?, ?)"
)
```

**Pair 3, the record.** SEARCH:
```python
def _row_to_snapshot(row: Any) -> SnapshotEntry:
```
REPLACE:
```python
@dataclass(frozen=True)
class NatureClearanceRecord:
    """AD-1341 S6: the Captain's clean slate at a reset, for ``nature_clearances``: what is cleared, never content."""

    timeline_id: str
    reset_tier: int
    cleared: tuple[str, ...]
    procedure_count: int

    def __post_init__(self) -> None:
        if type(self.timeline_id) is not str:
            raise ValueError("AD-1341 S6: timeline_id is a string (empty when the ship has no instance id)")
        if type(self.reset_tier) is not int or self.reset_tier not in (2, 3):  # AD-1341 S6: tier 1 keeps the crew
            raise ValueError("AD-1341 S6: a clean slate is part of a reset of tier 2 or 3")
        if type(self.cleared) is not tuple or any(type(item) is not str or not item.strip() for item in self.cleared):
            raise ValueError("AD-1341 S6: cleared is a tuple of data-directory names")
        if type(self.procedure_count) is not int or self.procedure_count < -1:
            raise ValueError("AD-1341 S6: procedure_count is a count, or -1 when the store could not be counted")


def _row_to_snapshot(row: Any) -> SnapshotEntry:
```

**Pair 4, the write.** SEARCH:
```python
        if row is None:
            return None
        logger.warning("AD-1341 S6: the Captain erased Ship's Records snapshot %d", snapshot_id)
        return _row_to_snapshot(row)
```
REPLACE:
```python
        if row is None:
            return None
        logger.warning("AD-1341 S6: the Captain erased Ship's Records snapshot %d", snapshot_id)
        return _row_to_snapshot(row)

    async def record_nature_clearance(self, clearance: NatureClearanceRecord) -> int:
        """Record the Captain's clean slate before it deletes nature; reached only from ``probos reset``."""
        if type(clearance) is not NatureClearanceRecord:
            raise TypeError("AD-1341 S6: record_nature_clearance takes a NatureClearanceRecord")
        params = (
            clearance.timeline_id.strip(), clearance.reset_tier, json.dumps(list(clearance.cleared)),
            clearance.procedure_count, time.time(),
        )
        async with self._write_lock:  # S1 D16: the marker commits or rolls back alone
            if not self._db:
                raise RuntimeError("ArchiveLedger not initialized")
            try:
                cursor = await self._db.execute(_NATURE_CLEARANCE_SQL, params)
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        logger.warning("AD-1341 S6: the Captain's clean slate is recorded (tier %d)", clearance.reset_tier)
        return cursor.lastrowid
```

**Pair 5, `json`.** SEARCH:
```python
import asyncio
import logging
import time
from dataclasses import dataclass
```
REPLACE:
```python
import asyncio
import json
import logging
import time
from dataclasses import dataclass
```

### 7.16 `src/probos/knowledge/nature_description.py` (M3)

The marker's count. SEARCH (M2's text):
```python
    facts = tuple(ProcedureFact.from_row(row) for row in rows)
    return describe_nature(timeline_id, started, facts, developed=developed, active=active)
```
REPLACE:
```python
    facts = tuple(ProcedureFact.from_row(row) for row in rows)
    return describe_nature(timeline_id, started, facts, developed=developed, active=active)


async def count_procedures(db_path: Path, open_read_only: Callable[[str], Awaitable[DatabaseConnection]]) -> int:
    """AD-1341 S6 (M3): how many procedures the store holds, for the clean slate's marker; 0 with no store.

    Opened read-only, as ``nature_description_record`` does; any error propagates.
    """
    if not db_path.is_file():
        return 0
    db = await open_read_only(str(db_path))
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM procedure_records")
        return int((await cursor.fetchone())[0])
    finally:
        await db.close()
```

### 7.17 `src/probos/__main__.py` (M3)

Twenty-four pairs, in file order (A2 added pairs 0, 10a and 12a to 12h, and rewrote pairs 9, 10, 11 and 13; A4 rewrote pairs 10 and 12e).

**Pair 0, the close's type for the annotations (A2).** SEARCH (M1's text):
```python
    from probos.knowledge.archive_store import ArchiveStore, PromotionRecord, SourceState
```
REPLACE:
```python
    from probos.knowledge.archive_store import ArchiveStore, GenerationRecord, PromotionRecord, SourceState
```

**Pair 1, the display helpers and the confirmation's signature.** SEARCH:
```python
def _show_confirmation_prompt(tier: int, data_dir: Path, active_task_count: int, console: Console) -> bool:
```
REPLACE:
```python
#: AD-1341 S6: the data directory's nature, which only --clean-slate clears (the procedure store, ``runtime.py``).
_NATURE_DIR = "procedures"


def _nature_rows(table: Table, data_dir: Path, clean_slate: bool) -> None:
    """AD-1341 S6: what ``--clean-slate`` clears, as the confirmation and the dry run show it."""
    if clean_slate:
        table.add_row("\n[bold]Nature (--clean-slate)[/bold]", "", "")
        table.add_row(
            f"  • {_NATURE_DIR}/", "Cognitive JIT procedures, their challengers and index",
            _get_file_size(data_dir / _NATURE_DIR),
        )


def _nature_preserved(clean_slate: bool) -> list[tuple[str, str, str]]:
    """AD-1341 S6: nature kept (without ``--clean-slate``) and the skill catalog, which no reset touches."""
    kept = [] if clean_slate else [(f"{_NATURE_DIR}/", "Cognitive JIT procedures: nature, kept by design", "")]
    return [*kept, ("config/skills/", "Skill catalog: part of the installation, never cleared", "")]


def _show_confirmation_prompt(
    tier: int, data_dir: Path, active_task_count: int, console: Console, *, clean_slate: bool = False,
) -> bool:
```

**Pair 2, the confirmation's cleared rows.** SEARCH:
```python
        for name, purpose, size in items:
            table.add_row(f"  • {name}", purpose, size)

    # What will be preserved
```
REPLACE:
```python
        for name, purpose, size in items:
            table.add_row(f"  • {name}", purpose, size)
    _nature_rows(table, data_dir, clean_slate)  # AD-1341 S6: the confirmation names what a clean slate clears

    # What will be preserved
```

**Pair 3, the confirmation's kept rows.** SEARCH:
```python
    # Always preserved
    preserved_items.append(("archives/", "Ward Room backups", ""))
```
REPLACE:
```python
    # Always preserved
    preserved_items.append(("archives/", "Ward Room backups", ""))
    preserved_items += _nature_preserved(clean_slate)  # AD-1341 S6: the confirmation names nature kept
```

**Pair 4, the dry run's signature.** SEARCH:
```python
def _show_dry_run(tier: int, data_dir: Path, active_task_count: int, console: Console) -> None:
```
REPLACE:
```python
def _show_dry_run(
    tier: int, data_dir: Path, active_task_count: int, console: Console, *, clean_slate: bool = False,
) -> None:
```

**Pair 5, the dry run's cleared rows.** SEARCH:
```python
        for name, purpose, size in items:
            table.add_row(f"  • {name}", purpose, size)

    preserved_items = []
```
REPLACE:
```python
        for name, purpose, size in items:
            table.add_row(f"  • {name}", purpose, size)
    _nature_rows(table, data_dir, clean_slate)  # AD-1341 S6: the dry run names what a clean slate clears

    preserved_items = []
```

**Pair 6, the dry run's kept rows.** SEARCH:
```python
            preserved_items.append((dname + "/", _file_purpose(dname), ""))
    preserved_items.append(("archives/", "Ward Room backups", ""))
```
REPLACE:
```python
            preserved_items.append((dname + "/", _file_purpose(dname), ""))
    preserved_items.append(("archives/", "Ward Room backups", ""))
    preserved_items += _nature_preserved(clean_slate)  # AD-1341 S6: the dry run names nature kept
```

**Pair 7, the exit codes.** SEARCH:
```python
    0 done, declined or a dry run; 1 refused with nothing deleted (a vessel owns the data directory, the Ship's
    Archive lies inside what the reset deletes, or the promotion of a tier 2 or 3 reset failed); 2 a
    ``--skip-promotion`` without a usable reason.
```
REPLACE:
```python
    0 done, declined or a dry run; 1 refused with nothing deleted (a vessel owns the data directory, the Ship's
    Archive lies inside what the reset deletes, or the promotion of a tier 2 or 3 reset failed; AD-1341 S6: or its
    snapshot, or a ``--clean-slate`` that could not be recorded or finished, or the generation's close, before the
    tier loop; AD-1341 S6 A2: or a refusal its preflight knows before anything is written); 2 a
    ``--skip-promotion`` without a usable reason, or a ``--clean-slate`` with ``--soft`` or a disabled archive.
```

**Pair 8, `--clean-slate` needs tier 2 or 3.** SEARCH:
```python
            console.print(f"[red]✗[/red] {problem}")
            return 2

    # Load config to find knowledge repo_path
```
REPLACE:
```python
            console.print(f"[red]✗[/red] {problem}")
            return 2
    clean_slate = bool(getattr(args, 'clean_slate', False))  # AD-1341 S6: the Captain's opt-in reset of nature
    if clean_slate and tier < 2:  # AD-1341 S6: --soft keeps the crew, so there is no new crew to start clean
        console.print("[red]✗[/red] --clean-slate applies to a reset of tier 2 or above; --soft keeps the crew.")
        return 2

    # Load config to find knowledge repo_path
```

**Pair 9, the archive to record it in, and `procedures/` among what the overlap protects the archive from (A2, C-F1).** SEARCH:
```python
    # AD-1341 S1 A4 (F3): refuse a reset that would delete the Ship's Archive. Every tier and a dry run too, before
    # the scheduled-task read, the confirmation and the pidfile; nothing is opened or touched.
    overlap = _archive_reset_overlap(config, tier, data_dir, repo_path)
```
REPLACE:
```python
    if clean_slate and not config.archive.enabled:  # AD-1341 S6: a clean slate is never unrecorded
        console.print(
            "[red]✗[/red] --clean-slate records what it clears in the Ship's Archive, which is disabled "
            "(archive.enabled). Nothing was changed."
        )
        return 2

    # AD-1341 S1 A4 (F3): refuse a reset that would delete the Ship's Archive. Every tier and a dry run too, before
    # the scheduled-task read, the confirmation and the pidfile; nothing is opened or touched.
    overlap = _archive_reset_overlap(config, tier, data_dir, repo_path, clean_slate=clean_slate)  # AD-1341 S6 A2
```

**Pair 10, the preflight checks the procedure store's directory, and the dry run shows the clean slate (A2; A4 re-anchored on M1's pair 2).** SEARCH (M1's pair 2 text):
```python
    refusal = _reset_preflight(config, tier, data_dir, skip_reason)

    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        if refusal:  # AD-1341 S6 A4: a reset that would refuse does nothing, so its dry run reads nothing more
            console.print("  [yellow]⚠ This reset would refuse, writing and deleting nothing:[/yellow]")
            console.print(f"    {refusal}", markup=False, emoji=False)
            console.print("\n  [dim][DRY RUN] No changes made.[/dim]")
            return 0  # AD-1341 S6 A4 (R2-B1, C-R2-F1): no tier table, plan or description reads the refused path
        _show_dry_run(tier, data_dir, active_task_count, console)
```
REPLACE:
```python
    refusal = _reset_preflight(config, tier, data_dir, skip_reason, clean_slate=clean_slate)

    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        if refusal:  # AD-1341 S6 A4: a reset that would refuse does nothing, so its dry run reads nothing more
            console.print("  [yellow]⚠ This reset would refuse, writing and deleting nothing:[/yellow]")
            console.print(f"    {refusal}", markup=False, emoji=False)
            console.print("\n  [dim][DRY RUN] No changes made.[/dim]")
            return 0  # AD-1341 S6 A4 (R2-B1, C-R2-F1): no tier table, plan or description reads the refused path
        _show_dry_run(tier, data_dir, active_task_count, console, clean_slate=clean_slate)
```

**Pair 10a, the confirmation shows it.** SEARCH:
```python
    if not getattr(args, 'yes', False):
        if not _show_confirmation_prompt(tier, data_dir, active_task_count, console):
```
REPLACE:
```python
    if not getattr(args, 'yes', False):
        if not _show_confirmation_prompt(tier, data_dir, active_task_count, console, clean_slate=clean_slate):
```

**Pair 11, the clean slate before the tier loop, and the generation's close last (A2, C-F3).** SEARCH:
```python
        promote_first = tier >= 2  # AD-1341 S1: tier 1 keeps the crew, so it has nothing to promote
        if promote_first and not _promote_before_reset(config, tier, data_dir, skip_reason, console):
            console.print("[red]✗[/red] probos reset refused before deleting anything.")
            return 1  # AD-1341 S1: refused before the tier loop; nothing was deleted

        # ── Execute reset ──
```
REPLACE:
```python
        promote_first = tier >= 2  # AD-1341 S1: tier 1 keeps the crew, so it has nothing to promote
        promoted, closing = (  # AD-1341 S6 A2 (C-F3): the generation's close is recorded last, below
            _promote_before_reset(config, tier, data_dir, skip_reason, console) if promote_first else (True, None)
        )
        if not promoted:
            console.print("[red]✗[/red] probos reset refused before deleting anything.")
            return 1  # AD-1341 S1: refused before the tier loop; nothing was deleted
        # AD-1341 S6: --clean-slate clears nature after the promotion (which described it) and before the tier loop, so
        # a failure here leaves every crew file in place and the same command finishes it.
        if clean_slate and not _clear_nature(config, tier, data_dir, console):
            console.print("[red]✗[/red] probos reset refused before its tier loop; the crew's files are untouched.")
            return 1
        # AD-1341 S6 A2 (C-F3): the generation is closed only once everything before the tier loop has succeeded
        if closing is not None and not _close_generation(config, closing, console):
            console.print("[red]✗[/red] probos reset refused before its tier loop; run the same command again.")
            return 1

        # ── Execute reset ──
```

**Pair 12, the summary says what became of nature.** SEARCH:
```python
    preserved.append("archives/")
    console.print(f"\n  Preserved: {', '.join(preserved)}")
```
REPLACE:
```python
    preserved.append("archives/")
    console.print(f"\n  Preserved: {', '.join(preserved)}")
    if clean_slate:  # AD-1341 S6
        console.print("  Nature cleared (--clean-slate): procedures/ (Cognitive JIT procedures)")
    else:
        console.print("  Nature kept: procedures/ (Cognitive JIT procedures)")
    console.print("  The skill catalog (config/skills) is part of the installation; no reset touches it.")
```

**Pair 12a, the overlap's flag (A2, C-F1).** SEARCH (M1's text):
```python
def _archive_reset_overlap(config: SystemConfig, tier: int, data_dir: Path, repo_path: Path) -> str:
```
REPLACE:
```python
def _archive_reset_overlap(
    config: SystemConfig, tier: int, data_dir: Path, repo_path: Path, *, clean_slate: bool = False,
) -> str:
```

**Pair 12b, the clean slate's target (A2, C-F1); not added to `RESET_TIERS`.** SEARCH (M1's text):
```python
        if "ontology_instance_id" in specials:
            targets.append(data_dir / "ontology" / "instance_id")
    for target in targets:
        resolved = os.path.normcase(str(target.resolve()))
        within = resolved.rstrip(os.sep) + os.sep
```
REPLACE:
```python
        if "ontology_instance_id" in specials:
            targets.append(data_dir / "ontology" / "instance_id")
    if clean_slate:  # AD-1341 S6 A2: --clean-slate deletes the procedure store's directory too (C-F1)
        targets.append(data_dir / _NATURE_DIR)
    for target in targets:
        resolved = os.path.normcase(str(target.resolve()))
        within = resolved.rstrip(os.sep) + os.sep
```

**Pair 12c, the promotion returns the generation's close (A2, C-F3).** SEARCH (S1's text):
```python
def _promote_before_reset(
    config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None, console: Console,
) -> bool:
    """Promote what the crew published into the Ship's Archive before a reset of tier 2 or above.

    True when the reset may go on; False, having said why, when it must not, with nothing deleted. With the
    archive disabled there is nowhere to promote to: a notice, and True (D13). That check comes before the one
    ``asyncio.run``, so a caller already inside an event loop with the archive disabled
    (``tests/test_bf902_fts_reconciliation.py``) never starts a second loop.
    """
    from rich.markup import escape

    if not config.archive.enabled:
        console.print(
            "[yellow]⚠ The Ship's Archive is disabled (archive.enabled): "
            "nothing is promoted before this reset.[/yellow]"
        )
        return True
    try:
        timeline_id = _read_instance_id(data_dir)  # before the tier loop deletes it
        proceed, message = asyncio.run(_promote_into_archive(config, tier, data_dir, timeline_id, skip_reason))
    except Exception as exc:  # any failure refuses the reset, and the Captain sees why
        console.print(
            f"[red]✗[/red] Ship's Archive promotion failed: {escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return False  # AD-1341 S1: a failed promotion refuses the reset
    console.print(f"  {escape(message)}" if proceed else f"[red]✗[/red] {escape(message)}")
    return proceed
```
REPLACE:
```python
def _promote_before_reset(
    config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None, console: Console,
) -> tuple[bool, GenerationRecord | None]:
    """Promote what the crew published into the Ship's Archive before a reset of tier 2 or above.

    (True, the generation's close) when the reset may go on; (False, None), having said why, when it must not, with
    nothing deleted. AD-1341 S6 A2 (C-F3): the close is returned, not recorded: ``_cmd_reset`` records it with
    ``_close_generation`` once any clean slate has finished, so no generation is closed while its crew's files
    remain; None when there is nothing to close. With the archive disabled there is nowhere to promote to: a notice,
    and (True, None) (D13). That check comes before the one ``asyncio.run``, so a caller already inside an event loop
    with the archive disabled (``tests/test_bf902_fts_reconciliation.py``) never starts a second loop.
    """
    from rich.markup import escape

    if not config.archive.enabled:
        console.print(
            "[yellow]⚠ The Ship's Archive is disabled (archive.enabled): "
            "nothing is promoted before this reset.[/yellow]"
        )
        return True, None
    try:
        timeline_id = _read_instance_id(data_dir)  # before the tier loop deletes it
        proceed, message, closing = asyncio.run(
            _promote_into_archive(config, tier, data_dir, timeline_id, skip_reason)
        )
    except Exception as exc:  # any failure refuses the reset, and the Captain sees why
        console.print(
            f"[red]✗[/red] Ship's Archive promotion failed: {escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return False, None  # AD-1341 S1: a failed promotion refuses the reset
    console.print(f"  {escape(message)}" if proceed else f"[red]✗[/red] {escape(message)}")
    return proceed, closing if proceed else None
```

**Pair 12d, the promotion's signature and the no-instance-id branch.** SEARCH (S1's text):
```python
) -> tuple[bool, str]:
    """The promotion run, or the recorded skip: (the reset may go on, what to tell the Captain).

    Raises on any failure, and closes the archive on every exit. Without an instance id nothing can be
    attributed (D9): anything to promote refuses, and a directory with nothing to promote has no generation to
    record, so nothing is opened.
    """
    from probos.knowledge.archive_promotion import plan_promotion, promote_ship_records
    from probos.knowledge.archive_store import GenerationOutcome, GenerationRecord

    records = _reset_records_store(config, data_dir)
    if skip_reason is None and not timeline_id:
        plan = await plan_promotion(records, timeline_id=_UNATTRIBUTED_TIMELINE)
        if plan.records:  # AD-1341 S1: nothing can be attributed without an instance id
            return False, (
                f"No instance id: {len(plan.records)} record(s) cannot be attributed to a timeline. "
                "Pass --skip-promotion REASON to reset without promoting them."
            )
        return True, "No instance id and nothing to promote: no generation is recorded."
```
REPLACE:
```python
) -> tuple[bool, str, GenerationRecord | None]:
    """The promotion run, or the skip: (the reset may go on, what to tell the Captain, the generation's close).

    Raises on any failure, and closes the archive on every exit. Without an instance id nothing can be
    attributed (D9): anything to promote refuses, and a directory with nothing to promote has no generation to
    record, so nothing is opened. AD-1341 S6 A2 (C-F3): the close (promoted or skipped) is returned, never recorded
    here: ``_cmd_reset`` records it with ``_close_generation`` once any clean slate has finished.
    """
    from probos.knowledge.archive_promotion import plan_promotion, promote_ship_records
    from probos.knowledge.archive_store import GenerationOutcome, GenerationRecord

    records = _reset_records_store(config, data_dir)
    if skip_reason is None and not timeline_id:
        plan = await plan_promotion(records, timeline_id=_UNATTRIBUTED_TIMELINE)
        if plan.records:  # AD-1341 S1: nothing can be attributed without an instance id
            return False, (
                f"No instance id: {len(plan.records)} record(s) cannot be attributed to a timeline. "
                "Pass --skip-promotion REASON to reset without promoting them."
            ), None
        return True, "No instance id and nothing to promote: no generation is recorded.", None
```

**Pair 12e, the skip's close is returned.** SEARCH (M1's pair 4 text):
```python
            await archive.record_generation(skipped)
            also = " The Ship's Records snapshot is skipped with it." if tier >= 3 else ""  # AD-1341 S6
            return True, f"Ship's Archive promotion skipped; the reason is recorded: {skip_reason.strip()}{also}"
```
REPLACE:
```python
            also = " The Ship's Records snapshot is skipped with it." if tier >= 3 else ""  # AD-1341 S6
            message = (  # AD-1341 S6 A4 (C-R2-F2): printed before the clearance and the close, so "will be"
                f"Ship's Archive promotion skipped; the reason will be recorded with the generation's close: "
                f"{skip_reason.strip()}{also}"
            )
            return True, message, skipped  # AD-1341 S6 A2 (C-F3): _close_generation records it, after any clean slate
```

**Pair 12f, the promotion's close is returned.** SEARCH (S1's and M1's text):
```python
            withheld=len(promoted.withheld),
        )
        await archive.record_generation(closed)
    finally:
        await archive.close()
    return True, (
        f"Ship's Archive: {len(promoted.created)} promoted, {len(promoted.present)} already archived, "
        f"{len(promoted.erased)} erased by the Captain, {len(promoted.vetoed)} vetoed by the Captain, "
        f"{len(promoted.withheld)} withheld (timeline {timeline_id})."
    ) + "".join(f"\n  {note}" for note in notes)
```
REPLACE:
```python
            withheld=len(promoted.withheld),
        )  # AD-1341 S6 A2 (C-F3): returned; _close_generation records it after any clean slate
    finally:
        await archive.close()
    message = (
        f"Ship's Archive: {len(promoted.created)} promoted, {len(promoted.present)} already archived, "
        f"{len(promoted.erased)} erased by the Captain, {len(promoted.vetoed)} vetoed by the Captain, "
        f"{len(promoted.withheld)} withheld (timeline {timeline_id})."
    ) + "".join(f"\n  {note}" for note in notes)
    return True, message, closed
```

**Pair 12g, the preflight's flag.** SEARCH (M1's text):
```python
def _reset_preflight(config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None) -> str:
```
REPLACE:
```python
def _reset_preflight(
    config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None, *, clean_slate: bool = False,
) -> str:
```

**Pair 12h, the preflight checks the procedure store's directory first (A2, B-F3, C-F2).** SEARCH (M1's text):
```python
    if tier < 3 or not config.archive.enabled or skip_reason is not None:
        return ""
    try:
        plan = _snapshot_plan(data_dir)
```
REPLACE:
```python
    if clean_slate:  # AD-1341 S6 A2: before the promotion reads the procedure store through it (B-F3, C-F2)
        problem = _nature_dir_problem(data_dir)
        if problem:
            return problem
    if tier < 3 or not config.archive.enabled or skip_reason is not None:
        return ""
    try:
        plan = _snapshot_plan(data_dir)
```

**Pair 13, the clean slate.** SEARCH:
```python
def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
```
REPLACE:
```python
def _clear_nature(config: SystemConfig, tier: int, data_dir: Path, console: Console) -> bool:
    """AD-1341 S6: ``--clean-slate``. Record the clearance in the Ship's Archive, then delete nature; True when done.

    Nature here is the procedure store's directory (``procedures/``: ``procedures.db``, the AD-1326 challenger ledger
    and the procedures' semantic index). The marker is written first, so nature is never deleted unrecorded. A link,
    a junction or a file at that name is refused, never followed. A deletion that fails part-way is reported; the
    reset refuses before its tier loop, and the same command finishes it. The skill catalog (``config/skills``), the
    Captain's grants, the Ship's Archive and its snapshots are never touched.
    """
    from rich.markup import escape

    procedures = data_dir / _NATURE_DIR
    problem = _nature_dir_problem(data_dir)  # AD-1341 S6 A2: asked again where it deletes
    if problem:
        console.print(f"[red]✗[/red] {escape(problem)}")
        return False
    try:
        count = asyncio.run(_record_nature_clearance(config, data_dir, tier))  # AD-1341 S6: the marker first
    except Exception as exc:  # the marker failed, so nothing is deleted; the Captain sees why
        console.print(
            f"[red]✗[/red] The clean slate could not be recorded, so nothing was cleared: "
            f"{escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return False
    try:
        if procedures.exists():
            shutil.rmtree(procedures, onerror=_force_remove_readonly)
    except OSError as exc:
        console.print(
            f"[red]✗[/red] The clean slate is recorded but did not finish: {escape(type(exc).__name__)}: "
            f"{escape(str(exc))}. Run the same command again."
        )
        return False  # AD-1341 S6: the deletion is recorded and unfinished; the reset refuses before its tier loop
    console.print(f"  Nature cleared (--clean-slate): {_NATURE_DIR}/ held {count} procedure(s); recorded in the Ship's Archive.")
    return True


async def _record_nature_clearance(config: SystemConfig, data_dir: Path, tier: int) -> int:
    """AD-1341 S6: the clean slate's marker: the timeline, the tier, what is cleared and the procedures it held."""
    from probos.knowledge.archive_ledger import NatureClearanceRecord
    from probos.knowledge.nature_description import PROCEDURES_DB, count_procedures

    try:
        count = await count_procedures(data_dir / PROCEDURES_DB, _open_read_only)
    except Exception:  # log-and-degrade: an unreadable store is still the Captain's to clear; the marker says -1
        logging.getLogger(__name__).warning(
            "AD-1341 S6: the procedure store could not be counted before the clean slate", exc_info=True,
        )
        count = -1
    cleared = (f"{_NATURE_DIR}/",) if (data_dir / _NATURE_DIR).exists() else ()
    ledger = await _open_ledger(config)
    try:
        await ledger.record_nature_clearance(NatureClearanceRecord(
            timeline_id=_read_instance_id(data_dir), reset_tier=tier, cleared=cleared, procedure_count=count,
        ))
    finally:
        await ledger.close()
    return count


def _nature_dir_problem(data_dir: Path) -> str:
    """AD-1341 S6 A2: why ``--clean-slate`` must not clear ``{data_dir}/procedures``, or ``""`` when it may.

    One ``lstat``, never followed: a link or junction there (it may lead out of the data directory), anything but a
    directory, or a name that cannot be inspected refuses. Nothing there is fine: nothing to clear. The preflight asks
    before the promotion reads the store through it (B-F3, C-F2); ``_clear_nature`` asks again where it deletes.
    """
    import stat

    from probos.knowledge.records_snapshot import is_link_status, lstat_or_none

    procedures = data_dir / _NATURE_DIR
    try:
        status = lstat_or_none(procedures)
    except OSError as exc:
        return f"{procedures} cannot be inspected ({exc}); --clean-slate clears nothing it cannot see."
    if status is None:
        return ""
    if is_link_status(status):  # AD-1341 S6: never followed out of the data directory
        return f"{procedures} is a link; --clean-slate clears only the data directory's own."
    if not stat.S_ISDIR(status.st_mode):  # AD-1341 S6 A2: a file at that name is refused too
        return f"{procedures} is not the procedure store's directory; nothing was cleared."
    return ""


def _close_generation(config: SystemConfig, closing: GenerationRecord, console: Console) -> bool:
    """AD-1341 S6 A2 (C-F3): record the generation's close, last before the tier loop; True when recorded.

    After the promotion, the snapshot and any clean slate have succeeded, so the Ship's Archive never shows a
    generation closed while its crew's files remain. A failure refuses the reset before its tier loop; the same
    command finishes it (the promotion is idempotent, the description is kept once per generation).
    """
    from rich.markup import escape

    try:
        asyncio.run(_record_generation(config, closing))
    except Exception as exc:  # the close failed; the reset refuses and the Captain sees why
        console.print(
            f"[red]✗[/red] The generation's close could not be recorded: {escape(type(exc).__name__)}: "
            f"{escape(str(exc))}"
        )
        return False  # AD-1341 S6 A2: not closed; the reset refuses before its tier loop
    return True


async def _record_generation(config: SystemConfig, closing: GenerationRecord) -> None:
    """AD-1341 S6 A2: S1's ``record_generation``, on its own archive connection; the archive is closed on every exit."""
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        await archive.record_generation(closing)
    finally:
        await archive.close()


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
```

**Pair 14, the flag.** SEARCH:
```python
        help="AD-1341: reset without promoting Ship's Records into the Ship's Archive first; "
             "the reason (1-500 characters) is recorded",
    )
```
REPLACE:
```python
        help="AD-1341: reset without promoting Ship's Records into the Ship's Archive first; "
             "the reason (1-500 characters) is recorded",
    )
    reset_parser.add_argument(
        "--clean-slate", action="store_true",
        help="AD-1341 S6: with tier 2 or 3, also clear nature (the Cognitive JIT procedure store), recorded first",
    )
```

### 7.18 New file: `tests/test_ad1341_s6_clean_slate.py` (M3)

```python
"""AD-1341 S6 (#1569), M3: ``probos reset --clean-slate`` clears nature, recorded first, and nothing else.

Real objects: the real ``_cmd_reset`` and ``main`` on a temporary data directory, a ``procedures.db`` with the
procedure store's own schema, the real ``ArchiveStore`` and ``ArchiveLedger``. The config loader is the one stand-in;
a deletion or a marker that fails is injected, because the platform cannot fail one on demand. No test reaches a real
data directory (the autouse fixture), and nothing here clears anything outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import asyncio
import io
import os
import sqlite3
import stat
import sys
import types
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import probos
from probos import __main__ as cli
from probos.knowledge.archive_ledger import ArchiveLedger, NatureClearanceRecord
from probos.cognitive.procedure_store import _SCHEMA as _PROCEDURE_SCHEMA
from probos.config import ArchiveConfig, KnowledgeConfig, SystemConfig
from probos.knowledge.archive_promotion import promote_nature_description
from probos.knowledge import records_snapshot
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.nature_description import PROCEDURES_DB, describe_nature
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_SHIP = "ship-did-alpha-0001"
_BOOT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_B = _BOOT.timestamp()
_ROWS = (
    {"id": "p-0", "name": "Inherited routine", "created_at": _B - 86400.0},
    {"id": "p-1", "name": "Coolant drift triage", "created_at": _B + 60.0, "total_completions": 8},
    {"id": "p-2", "name": "Sensor first", "evolution_type": "FIX", "created_at": _B + 120.0},
    {"id": "p-3", "name": "Purge before isolating", "is_negative": 1, "created_at": _B + 180.0},
)
#: Data-directory files no reset tier lists and the clean slate must leave alone.
_KEPT_STORES = ("cognitive_skills.db", "skill_grants.db", "profile_qualifications.db")


@pytest.fixture(autouse=True)
def _no_real_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every platform data and home path points under ``tmp_path``, and the CLI's default data directory raises."""
    home = tmp_path / "platform"
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(home / name.lower()))

    def _refuse() -> Path:
        raise AssertionError("AD-1341 S6: a test reached the platform data directory")

    monkeypatch.setattr(cli, "_default_data_dir", _refuse)


def _archive_db(tmp_path: Path) -> Path:
    return tmp_path / "archive" / "archive.db"


def _config(tmp_path: Path, *, archive_enabled: bool = True) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=archive_enabled, db_path=str(_archive_db(tmp_path)))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    id_file = data_dir / "ontology" / "instance_id"
    id_file.write_text(f"{_SHIP}\n", encoding="utf-8")
    os.utime(id_file, (_B, _B))  # the ship's first boot
    for name in ("events.db", "trust.db", "ward_room.db"):  # tiers 1, 2 and 3
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


def _nature(data_dir: Path) -> None:
    """The procedure store's directory as the vessel leaves it: the index, the challenger ledger, the semantic index."""
    path = data_dir / PROCEDURES_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_PROCEDURE_SCHEMA)
        for row in _ROWS:
            columns, marks = ", ".join(row), ", ".join("?" for _ in row)
            connection.execute(f"INSERT INTO procedure_records ({columns}) VALUES ({marks})", tuple(row.values()))
        connection.commit()
    finally:
        connection.close()
    (path.parent / "procedures_challenges.db").write_bytes(b"ledger")
    (path.parent / "chroma").mkdir()
    (path.parent / "chroma" / "index.bin").write_bytes(b"index")


def _tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()
    }


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None, "clean_slate": False,
    }
    values.update(flags)
    return cli._cmd_reset(Namespace(**values))


def _link_dir(link: Path, target: Path) -> None:
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this host cannot create a directory link: {exc}")


async def _an_earlier_entry(tmp_path: Path, archive: Path | None = None) -> None:
    store = ArchiveStore(str(archive or _archive_db(tmp_path)), connection_factory=default_factory)
    await store.initialize()
    try:
        await promote_nature_description(store, describe_nature("ship-did-earlier-0000", _BOOT, (), developed=1, active=0))
    finally:
        await store.close()


@pytest.mark.parametrize("full", [False, True], ids=["tier2", "tier3"])
def test_a_clean_slate_describes_records_and_clears_nature_and_touches_nothing_else(
    full: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    for name in _KEPT_STORES:
        (data_dir / name).write_bytes(name.encode("utf-8"))
    (data_dir / "archives").mkdir()
    (data_dir / "archives" / "ward_room_2026-01-01_000000.db").write_bytes(b"an older backup")
    captain = tmp_path / "captain" / "system.yaml"
    captain.parent.mkdir()
    captain.write_text("archive:\n  enabled: true\n", encoding="utf-8")
    config = _config(tmp_path)
    asyncio.run(_an_earlier_entry(tmp_path))
    before = _tree(data_dir)

    assert _reset(monkeypatch, config, data_dir, full=full, clean_slate=True) == 0

    assert not (data_dir / "procedures").exists()
    archive = _archive_db(tmp_path)
    assert _rows(archive, "SELECT timeline_id, reset_tier, cleared, procedure_count FROM nature_clearances") == [
        (_SHIP, 3 if full else 2, '["procedures/"]', 4),
    ]
    assert _rows(archive, "SELECT timeline_id FROM archive WHERE source_kind = 'nature_description' ORDER BY id") == [
        ("ship-did-earlier-0000",), (_SHIP,),
    ]  # the earlier entry kept, and this crew's nature described before it was cleared
    deleted = {"events.db", "trust.db", "ontology/instance_id"} | ({"ward_room.db"} if full else set())
    after = {
        path: content for path, content in _tree(data_dir).items()
        if path != "probos.pid.lock" and not (path.startswith("archives/ward_room_") and path not in before)
    }
    assert after == {
        path: content for path, content in before.items() if path not in deleted and not path.startswith("procedures/")
    }
    assert captain.read_text(encoding="utf-8") == "archive:\n  enabled: true\n"
    assert _tree(tmp_path / "knowledge") == {}
    assert "Nature cleared (--clean-slate): procedures/" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [{"soft": True}, {}, {"full": True}], ids=["tier1", "tier2", "tier3"])
def test_without_clean_slate_nature_persists_at_every_tier(
    flags: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    before = _tree(data_dir / "procedures")

    assert _reset(monkeypatch, _config(tmp_path), data_dir, **flags) == 0

    assert _tree(data_dir / "procedures") == before
    assert "Nature kept: procedures/ (Cognitive JIT procedures)" in capsys.readouterr().out
    if _archive_db(tmp_path).exists():
        assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM nature_clearances") == [(0,)]


@pytest.mark.parametrize("case", ["soft", "archive-disabled"])
def test_a_clean_slate_that_does_not_apply_or_cannot_be_recorded_changes_nothing(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    before = _tree(data_dir)
    config = _config(tmp_path, archive_enabled=case != "archive-disabled")

    assert _reset(monkeypatch, config, data_dir, clean_slate=True, **({"soft": True} if case == "soft" else {})) == 2

    assert _tree(data_dir) == before  # no pidfile lock either: refused before anything is opened
    assert not _archive_db(tmp_path).exists()


def test_an_interrupted_clean_slate_is_finished_by_running_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    config = _config(tmp_path)
    real_rmtree = cli.shutil.rmtree
    calls: list[Path] = []

    def _fails_once(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        if len(calls) == 1:
            (Path(path) / "procedures_challenges.db").unlink()  # part of it went before the failure
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cli.shutil, "rmtree", _fails_once)

    assert _reset(monkeypatch, config, data_dir, clean_slate=True) == 1
    assert "did not finish" in capsys.readouterr().out
    assert (data_dir / "trust.db").is_file() and (data_dir / "ontology" / "instance_id").is_file()  # no tier loop
    assert (data_dir / PROCEDURES_DB).is_file()
    assert _rows(_archive_db(tmp_path), "SELECT procedure_count FROM nature_clearances") == [(4,)]  # recorded first
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]  # A2 (C-F3): not closed yet

    assert _reset(monkeypatch, config, data_dir, clean_slate=True) == 0  # the same command finishes it
    assert not (data_dir / "procedures").exists() and not (data_dir / "trust.db").exists()
    assert _rows(_archive_db(tmp_path), "SELECT procedure_count FROM nature_clearances ORDER BY id") == [(4,), (4,)]
    assert _rows(_archive_db(tmp_path), "SELECT timeline_id, reset_tier, outcome FROM generations") == [
        (_SHIP, 2, "promoted"),
    ]  # closed once, after the clearance finished


def test_a_clean_slate_whose_marker_cannot_be_written_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    before = _tree(data_dir / "procedures")

    async def _refuses(self: ArchiveLedger, clearance: NatureClearanceRecord) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ArchiveLedger, "record_nature_clearance", _refuses)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, clean_slate=True) == 1

    assert "could not be recorded" in capsys.readouterr().out
    assert _tree(data_dir / "procedures") == before
    assert (data_dir / "trust.db").is_file()


def test_the_dry_run_and_the_confirmation_name_what_a_clean_slate_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    config = _config(tmp_path)

    assert _reset(monkeypatch, config, data_dir, dry_run=True, clean_slate=True) == 0
    out = capsys.readouterr().out
    assert "Nature (--clean-slate)" in out and "Cognitive JIT procedures, their challengers and index" in out

    assert _reset(monkeypatch, config, data_dir, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "Nature (--clean-slate)" not in out and "Cognitive JIT procedures: nature, kept by design" in out

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert _reset(monkeypatch, config, data_dir, yes=False, clean_slate=True) == 0  # declined
    assert "Nature (--clean-slate)" in capsys.readouterr().out
    assert (data_dir / PROCEDURES_DB).is_file() and not _archive_db(tmp_path).exists()


def _odd_procedures(shape: str, data_dir: Path, tmp_path: Path) -> Path:
    """At ``{data_dir}/procedures``: a junction to a sibling's real procedure store, or a file. Returns what must
    survive: the sibling, or the file."""
    if shape == "junction":
        sibling = tmp_path / "sibling"
        _nature(sibling)
        _link_dir(data_dir / "procedures", sibling / "procedures")
        return sibling
    (data_dir / "procedures").write_bytes(b"not the procedure store")
    return data_dir / "procedures"


def _kept(target: Path) -> Any:
    return _tree(target) if target.is_dir() else target.read_bytes()


def _archive_state(tmp_path: Path) -> list[list[tuple[Any, ...]]]:
    """Every row count a reset could change in the archive's file."""
    return [
        _rows(_archive_db(tmp_path), f"SELECT COUNT(*) FROM {table}")
        for table in ("archive", "generations", "archive_snapshots", "nature_clearances", "archive_vetoes")
    ]


@pytest.mark.parametrize("shape", ["junction", "file"])
def test_a_link_or_a_file_at_the_procedures_name_is_refused_before_anything_is_written(
    shape: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (B-F3, C-F2): refused by the preflight, before the promotion reads the store through it: nothing archived,
    described, recorded or closed, and the link's target or the file unchanged."""
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path)
    asyncio.run(_an_earlier_entry(tmp_path))
    archive_before = _archive_state(tmp_path)
    target = _odd_procedures(shape, data_dir, tmp_path)
    before = _kept(target)

    assert _reset(monkeypatch, config, data_dir, clean_slate=True) == 1

    assert _archive_state(tmp_path) == archive_before
    assert _kept(target) == before
    assert (data_dir / "trust.db").is_file() and (data_dir / "ontology" / "instance_id").is_file()
    expected = "is a link" if shape == "junction" else "is not the procedure store's directory"
    assert expected in capsys.readouterr().out


@pytest.mark.parametrize("shape", ["junction", "file"])
def test_the_clearance_refuses_a_link_or_a_file_again_where_it_deletes(shape: str, tmp_path: Path) -> None:
    """A2: ``_clear_nature`` asks again (the preflight asked first), so a change between the two is refused before
    the marker, and nothing is followed or deleted."""
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path)
    target = _odd_procedures(shape, data_dir, tmp_path)
    before = _kept(target)

    assert cli._clear_nature(config, 2, data_dir, Console(file=io.StringIO(), width=200)) is False

    assert not _archive_db(tmp_path).exists()  # no marker
    assert _kept(target) == before


@pytest.mark.parametrize(
    "flags", [{"clean_slate": True}, {"clean_slate": True, "full": True}, {}], ids=["tier2", "tier3", "flag-off"],
)
def test_an_archive_inside_the_procedure_store_refuses_a_clean_slate(
    flags: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (C-F1): ``--clean-slate`` deletes ``procedures/``, so an archive there is inside what the reset deletes, at
    either tier and in the dry run; without the flag ``procedures/`` is kept, and the archive in it."""
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    archive = data_dir / "procedures" / "archive" / "archive.db"
    archive.parent.mkdir()
    (tmp_path / "knowledge").mkdir()
    config = SystemConfig(
        knowledge=KnowledgeConfig(repo_path=str(tmp_path / "knowledge")),
        archive=ArchiveConfig(enabled=True, db_path=str(archive)),
    )
    asyncio.run(_an_earlier_entry(tmp_path, archive))

    if flags:
        assert _reset(monkeypatch, config, data_dir, dry_run=True, **flags) == 1  # the dry run refuses too
        before = _tree(data_dir / "procedures")
        assert _reset(monkeypatch, config, data_dir, **flags) == 1
        assert "the Ship's Archive is inside what this reset deletes" in capsys.readouterr().out
        assert _tree(data_dir / "procedures") == before and (data_dir / "trust.db").is_file()
    else:
        assert _reset(monkeypatch, config, data_dir) == 0
    assert ("ship-did-earlier-0000",) in _rows(archive, "SELECT timeline_id FROM archive")


def test_a_skipped_promotion_is_closed_only_after_its_clean_slate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (C-F3): with ``--skip-promotion`` too, a clearance that fails leaves no generation closed; the rerun
    closes it once, as skipped. A4 (C-R2-F2): the skip's message is printed before the clearance and the close, so
    it says the reason will be recorded, never that it is."""
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    config = _config(tmp_path)
    real_rmtree = cli.shutil.rmtree
    calls: list[Path] = []

    def _fails_once(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        if len(calls) == 1:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cli.shutil, "rmtree", _fails_once)

    assert _reset(monkeypatch, config, data_dir, clean_slate=True, skip_promotion="drill") == 1
    out = capsys.readouterr().out
    assert "the reason is recorded" not in out  # A4 (C-R2-F2): no generation row holds it yet
    assert "the reason will be recorded with the generation's close: drill" in out
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]

    assert _reset(monkeypatch, config, data_dir, clean_slate=True, skip_promotion="drill") == 0
    assert _rows(_archive_db(tmp_path), "SELECT reset_tier, outcome, reason FROM generations") == [
        (2, "skipped", "drill"),
    ]


@pytest.mark.parametrize("full", [False, True], ids=["tier2", "tier3"])
def test_a_refused_dry_run_reads_nothing_through_the_procedures_link(
    full: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A4 (R2-B1, C-R2-F1): a dry run whose preflight refuses a link at ``procedures`` prints the refusal and nothing
    else. It neither sizes the refused directory nor opens ``procedures.db`` through it, so the link's WAL-mode
    target gains no ``-wal`` or ``-shm`` file and none of its text is shown."""
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path)
    sibling = _odd_procedures("junction", data_dir, tmp_path)
    store = sibling / PROCEDURES_DB
    connection = sqlite3.connect(str(store))
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)  # premise: the vessel's mode
    finally:
        connection.close()
    names = sorted(os.listdir(store.parent))
    before = _tree(sibling)
    opened: list[str] = []
    sized: list[Path] = []
    real_open, real_size = cli._open_read_only, cli._get_file_size

    async def _counted(path: str) -> Any:
        opened.append(path)
        return await real_open(path)

    def _measured(path: Path) -> str:
        sized.append(path)
        return real_size(path)

    monkeypatch.setattr(cli, "_open_read_only", _counted)
    monkeypatch.setattr(cli, "_get_file_size", _measured)

    assert _reset(monkeypatch, config, data_dir, dry_run=True, clean_slate=True, full=full) == 0

    assert opened == []  # 2a1b6319: procedures.db opened once, through the link, by the promotion plan
    assert [path for path in sized if path.name == "procedures"] == []
    assert sorted(os.listdir(store.parent)) == names and _tree(sibling) == before  # no -wal, no -shm
    out = capsys.readouterr().out
    assert "This reset would refuse" in out and "is a link" in out
    assert "Coolant drift triage" not in out  # none of the target's text
    assert not _archive_db(tmp_path).exists()


def _posix_stat() -> Any:
    """A POSIX build's ``stat`` module, stricter: no ``IO_REPARSE_TAG_*`` (Windows-only) and no ``FILE_ATTRIBUTE_*``.

    A5: ``Lib/stat.py`` defines the 17 ``FILE_ATTRIBUTE_*`` constants on every platform; they are removed here too,
    and no S6 module reads either set, so no result depends on the difference (A4).
    Swapped in for ``records_snapshot.stat`` only, never deleted from the interpreter's ``stat``."""
    return types.SimpleNamespace(**{
        name: value for name, value in vars(stat).items()
        if not name.startswith(("_", "IO_REPARSE_TAG_", "FILE_ATTRIBUTE_"))
    })


def test_a_clean_slate_needs_no_windows_only_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A4 (A-R2-F1): with ``records_snapshot`` seeing a POSIX build's ``stat``, the clean slate's checks judge
    ``procedures/`` by its mode and the reset clears it (on ``2a1b6319`` the preflight raised ``AttributeError``)."""
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    monkeypatch.setattr(records_snapshot, "stat", _posix_stat())

    assert _reset(monkeypatch, _config(tmp_path), data_dir, clean_slate=True) == 0

    assert not (data_dir / "procedures").exists()
    assert _rows(_archive_db(tmp_path), "SELECT procedure_count FROM nature_clearances") == [(4,)]


def test_only_the_cli_records_a_clean_slate() -> None:
    naming: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "record_nature_clearance") or (
                isinstance(node, ast.Constant) and node.value == "record_nature_clearance"
            ):
                naming.add(path.relative_to(_SRC).as_posix())
    assert naming == {"__main__.py"}


def test_main_parses_clean_slate(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Namespace] = []

    def _command(args: Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, "_cmd_reset", _command)
    monkeypatch.setattr("sys.argv", ["probos", "reset", "--yes", "--clean-slate"])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [args.clean_slate for args in seen] == [True]


@pytest.mark.parametrize(
    "change",
    [{"reset_tier": 1}, {"reset_tier": 4}, {"reset_tier": True}, {"procedure_count": -2}, {"procedure_count": 1.0},
     {"cleared": ["procedures/"]}, {"cleared": (" ",)}, {"timeline_id": None}],
    ids=["tier-1", "tier-4", "tier-bool", "count-below", "count-float", "cleared-list", "cleared-blank", "timeline"],
)
def test_a_clean_slate_marker_holds_only_what_it_may(change: dict[str, Any]) -> None:
    good: dict[str, Any] = {"timeline_id": _SHIP, "reset_tier": 2, "cleared": ("procedures/",), "procedure_count": 0}
    NatureClearanceRecord(**good)  # premise
    NatureClearanceRecord(**{**good, "timeline_id": "", "procedure_count": -1})  # no instance id; an unread store
    with pytest.raises(ValueError):
        NatureClearanceRecord(**{**good, **change})
```

The first S6 import is `from probos.knowledge.archive_ledger import ArchiveLedger, NatureClearanceRecord` (placed before `probos.cognitive`; keep that order).

## 8. Tracking (tracker pairs; M4's commit)

Written on the S5 repair candidate `4b3101f3`. The anchors are the title line (`PROGRESS.md:1`) and the heading every DECISIONS entry since 2026-10-17 has been inserted against (`DECISIONS.md:855`); S5's entries are above both (`PROGRESS.md:3`, `DECISIONS.md:845`) and neither pair touches them. If S5's round 2 rewrites its own entries, these anchors still hold. Set the date to the commit date.

**`PROGRESS.md`** (the new entry goes first, under the title). SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1341 S6 (2026-10-2X), #1569 slice 6 of 6 -- the `--full` Ship's Records snapshot, the nature description, and an opt-in `--clean-slate`.** A `--full` (tier 3) reset now keeps every Ship's Records file it deletes, except the git history (`.git/`) and the procedures' YAML copies (`procedures/`), as one ZIP file holding one BagIt bag (RFC 8493), at `ship-records-snapshots/{timeline}/{started}_{ended}.zip` beside the Ship's Archive's database. It is keyed by the ship's instance id (the ship DID is in `bag-info.txt`) and the generation's dates. The file is written under a temporary name, flushed, read back and checked, recorded in the archive's new content-free table `archive_snapshots`, then published by one hard link, which never replaces a name. Any failure refuses the reset with nothing deleted, and every refusal a reset can know beforehand (a link, junction or root that cannot be inspected; the bounds; no instance id; the archive or its snapshots inside or around what the reset deletes) comes before anything is written; the dry run says so and reads nothing more. Bounds: 100,000 files and 2 GiB; a link, a special file, an unreadable file or one that changes while it is copied refuses too. No agent, service or Oracle tier reads a snapshot; it holds every classification, as Ship's Records do. The reset names the Markdown files Ship's Records cannot list, which the snapshot now keeps (S1 register RA3-1 closes; F-649 closes at tier 3). `probos archive snapshots` lists them; `probos archive erase-snapshot ID --reason TEXT` records the erasure first, then deletes the file, and first any second name of it a publish could not remove. `--skip-promotion REASON` skips the snapshot too. Every tier 2 and 3 reset also archives one `nature_description` entry per generation (`ship`; a retried reset keeps the first): which Cognitive JIT procedures this crew developed since the ship's first boot, with each one's name, description, evolution, state, use counts and change summary, at most 900 characters, never a procedure's steps, with no model call. The Captain sees it in `pending` and `--dry-run` and can veto or erase it. Skills are not described: the catalog is part of the installation and keeps no durable record of who forged a skill. `--clean-slate` (tier 2 or 3, archive enabled) records a content-free marker in `nature_clearances`, then deletes `procedures/` (the procedure store, its challenger ledger and its index) before the tier loop; a failure refuses before the tier loop and the same command finishes it. A link, junction or file at `procedures`, or an archive inside it, refuses before anything is written, and the generation's close is recorded only after the clearance. It never touches `config/skills`, the Captain's skill grants, the archive, the snapshots or `archives/`. Two additive tables, `user_version` stays 1; one `SourceKind`; no config field, event type, API route or HXI view. New: `src/probos/knowledge/records_snapshot.py`, `src/probos/knowledge/archive_ledger.py`, `src/probos/knowledge/nature_description.py`, `tests/test_ad1341_s6_records_snapshot.py`, `tests/test_ad1341_s6_nature_description.py`, `tests/test_ad1341_s6_clean_slate.py`. The contract is `prompts/ad-1341-s6-records-snapshot-nature-and-clean-slate.md`.
```

**`DECISIONS.md`** (before the `### Explicit delegation models` heading, so after S5's entry). SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1341 S6 -- The `--full` Ship's Records snapshot, the nature description, and an opt-in `--clean-slate` (2026-10-2X, #1569 slice 6 of 6)

- *Scope.* Slice 6 of #1569 (Decision 2's snapshot, AD-524's item 1; the 2026-10-16 amendment's description entry and clean slate), three code commits and one tracker commit. Files: `knowledge/records_snapshot.py`, `knowledge/archive_ledger.py`, `knowledge/nature_description.py` (new), `knowledge/archive_store.py` (two tables, `SourceKind.NATURE_DESCRIPTION`), `knowledge/archive_promotion.py` (`promote_nature_description`, `review_nature_description`), `__main__.py`, `docs/development/store-baseline.yaml`, three new tests and one updated test. Contract: `prompts/ad-1341-s6-records-snapshot-nature-and-clean-slate.md`.
- *D2-D5 (the snapshot).* One ZIP file holding one BagIt bag, beside the archive's database, keyed `{timeline}/{started}_{ended}`, recorded by a content-free row. Not an archive entry: the Oracle's archive tier reads every row with no reader filter, so an entry would give draft, department and private notes to every later crew (S1 C1). It keeps every classification because no reader exists; any later reader (AD-524 items 2 and 3) must apply the classification rule. A `git bundle` (misses uncommitted notes) and a copied directory (not atomic) were rejected. `.git/` and `procedures/` are left out. 100,000 files and 2 GiB; links are never followed, by a rule that names nothing a POSIX build lacks (A4). The Captain may overrule and keep only `ship` and `fleet`.
- *D6 (order).* A preflight first refuses, before anything is written, whatever it can know: the snapshot's plan, root, key and destination; with `--clean-slate`, the shape of `procedures/`; and the archive and its snapshots against everything the reset deletes. Then: promote, read nature, snapshot (write, check, record, publish by a hard link that never replaces), archive the description, clear nature with `--clean-slate`, close the generation, then the tier loop. Any failure refuses with nothing deleted, so a generation is closed only with its snapshot in place and its clean slate done (A2). A dry run whose preflight refuses prints the refusal and reads nothing more (A4).
- *D7 (the ledger).* `ArchiveLedger`, a class of its own on its own connection, because `ArchiveStore` is at the SRP method trigger (15). The Captain's `erase-snapshot` marks the row before it deletes the file; a row is never deleted. A temporary name the publish could not remove after its link is the same file under a second name; the erasure removes it first and reports the erasure unfinished while either name remains (A4).
- *D8.* `--skip-promotion REASON` skips the snapshot (and the description) too: one audited escape. The Captain may overrule with a separate flag.
- *D10-D11 (the description).* One `ship` entry per generation (a retried reset keeps the first, whatever changed; `pending` and the veto show its whole text), built from `procedures.db` read-only, no model call, at most 900 characters so the whole entry fits one Oracle tool entry, never `content_snapshot`. One builder serves the reset, `--dry-run`, `pending` and `veto`; the veto is keyed by kind and reference, so it holds whatever the content is at the reset. Skills are not described (the catalog's `origin` is rewritten at every boot); the Captain may overrule once the origin is durable.
- *D12-D13 (`--clean-slate`).* A flag on tiers 2 and 3, not a tier 4. It clears `procedures/` only, after the promotion (whose description records what is cleared) and before the tier loop, with its marker written first. It needs the archive enabled. The skill catalog (files in the installation), `skill_grants.db` (the Captain's grants) and AD-1287's profiles are left alone; the Captain may overrule.
- *Disclosed effects.* A `--full` reset refuses in new cases (it fails closed), each before anything is written: a link, junction or special file in Ship's Records or at its root, a root that cannot be inspected, either bound, no instance id, and a link or junction at the snapshots directory or the timeline's directory; and, at publish, a file system without hard links under the archive. Every reset refuses when the archive or its snapshots directory is inside or around what it deletes, `procedures/` included with `--clean-slate`, which also refuses a link, junction or file at `procedures`. It copies up to 2 GiB synchronously. `archive_snapshots` and `nature_clearances` in the archive's file, `user_version` 1. `SourceKind` gains `nature_description`. `probos archive snapshots`, `probos archive erase-snapshot`, `probos reset --clean-slate`.
- *Reversal.* Revert the S6 commits. Snapshot files and their rows stay; the Captain deletes the directory by hand if wanted. Archived descriptions stay and read as before; `probos archive erase` removes one. A cleared procedure store is not restored by a revert: it was the Captain's opt-in deletion, recorded in `nature_clearances`.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M4's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the gate:** add a *Validation of record* bullet before AD-1341 S6's *Reversal* line: the campaign of record, its base tree, the sha256 of each §10 file and of the three new test files, and each row's first failing test. Add the same as a closing §16 of this contract, then regenerate the ledger.

**`docs/development/roadmap.md`:** no row; `AD-1341` does not appear there (S2 §8). **`docs/development/roadmap-era-5-completed.md:2523`** (AD-524's item 1) is a completed-era record and is not edited; the DECISIONS entry names AD-524's item 1.

**#1569:** S6 is the last slice. Closing the issue is the orchestrator's, after the gate and the register rows below are posted.

## 9. What this does NOT change

- `RESET_TIERS` and every tier's file list (the issue's "Do Not Build"). A tier deletes what it deleted; S6 adds what is kept first and one opt-in deletion.
- The pidfile (AD-816), the archive-inside-the-reset refusal (S1 A4; A2 extends it to the snapshots directory and, with `--clean-slate`, to `procedures/`), `--dry-run`'s rule that it opens no archive and takes no pidfile (the snapshot plan and the description read Ship's Records and `procedures.db` read-only), `--yes`, and the exit codes other than the new refusals (7.17 pair 7).
- S1's promotion, its key and idempotence; S2's label and generation numbering; S3's review, veto and `/forget` cascade; S4's notes and stand-down; S5's after-action report and continuous promotion (which never archives a description or takes a snapshot: it plans over Ship's Records only).
- `ArchiveStore`'s methods (none added), `promote_entry`, `erase_entry`, `veto_source`, `source_state`, `user_version` (stays 1), the Oracle and its tool's 1,200-character cut.
- The procedure store, its schema, `content_snapshot`, its YAML copies and AD-1326's challenger ledger: read read-only for the description, deleted only by `--clean-slate`.
- The skill catalog (`config/skills`, `cognitive_skills.db`), `skill_grants.db`, `skills.db` (AD-428, a tier 2 file as before), `profile_qualifications.db` (AD-1287).
- `ErasureManager` (AD-754): a snapshot holds no episode and is not an entry.
- AD-1265's backups (`*.db` only): a snapshot ZIP is not backed up; `archive.db` (with the two tables) is, as before.
- `config.py`, `config/system.yaml`, the AD-1185 manifest, the AD-1270 facade baseline and `config-reference.md`: no config field.
- No `EventType`, API route, HXI view, model call, federation path or agent write.
- `--skip-promotion` also skips the nature description, as it skips every promotion; with `--clean-slate` the marker is still written, so the clearance is recorded even when nothing is described (register R19).
- `probos reset` at tier 1 (no promotion, no close) and at tiers 2 and 3 without `--clean-slate`: the generation is closed after the promotion as before, now by `_close_generation` on a second archive connection (A2, register R37).
- A4: `--dry-run` without a refusal is unchanged (the tier table, the plan, the description, the snapshot plan); with one it prints only the refusal, still exit 0 and still opening no archive.
- A4: the publish protocol (a hard link, then the temporary name removed, a failure logged) and the erasure's marker-first order and path checks are unchanged; no row is deleted.
- A4: without `--clean-slate`, `probos archive pending` and `veto` still read `procedures.db` through a link at `procedures` (D12: only the clean slate refuses that shape).
- Out of scope (D18): a snapshot reader or view, `--verify`, restore, `scout_reports/` and `workforce.db` in the snapshot, automatic after-action triggers, a durable skill origin, fleet sharing.

## 10. Mutation rows (80 rows: 45 for M1, 16 for M2, 19 for M3; whole stripped lines, each occurring once in its file after §7)

One campaign on the assembled tree (M1 to M3 applied), after an unmutated baseline run of the three new test files and `tests/test_ad1341_s3_veto_store.py` that passes. Run each row against the named tests and restore the file before the next row. A row whose mutant makes a named test hang (none is expected) counts as killed only under the campaign's per-test timeout. Lines with no row, and why: the in-loop `copied > item.size` guard (outcome-equivalent, R24), the `is_file` refusal (POSIX-only, R23), `_snapshot_state`'s `(not a snapshot's name: never opened)` branch (covered by P-12's line in `_erase_snapshot`; the listing's branch is display only, R21), `count = -1` in `_record_nature_clearance` (log-and-degrade, constructor-pinned by C10 only, R22), and the `started is None` race in `_snapshot_ship_records` (R20). A2 adds no row for: the inspection-error branch of `_nature_dir_problem` and the preflight's `except` (an `OSError` other than absence; injected only, R28); the hard-link fallback's `except OSError` (a clause, pinned by X9b, whose `match="hard link"` fails if the clause goes); `_remove_quietly` after the link (log-and-degrade); and two orders no single-line mutant reverses: the description after the snapshot (N10) and the close after the clearance (C4, C13).

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| P-1 | M1 | `src/probos/knowledge/records_snapshot.py` | `if entry.is_symlink() or entry.is_junction():  # never followed: it may lead out of Ship's Records` | `if False:` | `test_a_link_inside_ship_records_is_never_followed`, `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| P-2 | M1 | `src/probos/knowledge/records_snapshot.py` | `if not (prefix == "" and entry.name in SNAPSHOT_EXCLUDED):  # .git/ and procedures/ stay out` | `if True:` | `test_the_plan_lists_every_file_but_git_and_procedures_within_its_bounds` |
| P-3 | M1 | `src/probos/knowledge/records_snapshot.py` | `if len(files) > SNAPSHOT_MAX_FILES or total > SNAPSHOT_MAX_BYTES:` | `if len(files) > SNAPSHOT_MAX_FILES:` | `test_the_plan_lists_every_file_but_git_and_procedures_within_its_bounds`, `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| P-4 | M1 | `src/probos/knowledge/records_snapshot.py` | `if len(files) > SNAPSHOT_MAX_FILES or total > SNAPSHOT_MAX_BYTES:` | `if len(files) >= SNAPSHOT_MAX_FILES or total >= SNAPSHOT_MAX_BYTES:` | `test_the_plan_lists_every_file_but_git_and_procedures_within_its_bounds` |
| P-5 | M1 | `src/probos/knowledge/records_snapshot.py` | `if copied != item.size:  # it shrank after it was listed` | `if False:` | `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| P-6 | M1 | `src/probos/knowledge/records_snapshot.py` | `if os.path.lexists(final):  # a snapshot is never written over` | `if False:` | `test_a_snapshot_is_never_written_over` |
| P-7 | M1 | `src/probos/knowledge/records_snapshot.py` | `os.link(self.temp_path, self.final_path)  # A2: no-replace on Windows and POSIX; an existing name refuses` | `os.replace(self.temp_path, self.final_path)` | `test_a_snapshot_is_never_written_over` |
| P-8 | M1 | `src/probos/knowledge/records_snapshot.py` | `if bag_zip.namelist() != expected:` | `if False:` | `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| P-9 | M1 | `src/probos/knowledge/records_snapshot.py` | `if _digest(bag_zip.open(f"{bag}/data/{item.path}")) != digests[item.path]:  # zipfile also checks each CRC` | `if False:` | `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| P-10 | M1 | `src/probos/knowledge/records_snapshot.py` | `return path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")` | `return path` | `test_a_prepared_snapshot_reads_back_as_written_and_is_published_once` |
| P-11 | M1 | `src/probos/knowledge/records_snapshot.py` | `if type(timeline_id) is not str or _TIMELINE_SEGMENT.fullmatch(timeline_id) is None:` | `if type(timeline_id) is not str:` | `test_an_instance_id_that_cannot_name_a_directory_refuses_the_snapshot` |
| P-12 | M1 | `src/probos/__main__.py` | `if not is_snapshot_relative_path(entry.relative_path):  # AD-1341 S6: a row never names a file outside the snapshots` | `if False:` | `test_an_erasure_never_deletes_a_file_outside_the_snapshots` |
| P-13 | M1 | `src/probos/__main__.py` | `await ledger.mark_snapshot_erased(snapshot_id, reason)  # the marker first` | `pass` | `test_the_captain_lists_and_erases_a_snapshot_with_the_marker_first` |
| P-14 | M1 | `src/probos/__main__.py` | `prepared.discard()` | `pass` | `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| P-15 | M1 | `src/probos/__main__.py` | `if not timeline_id or started is None:  # AD-1341 S6: no ship to key the snapshot by` | `if False:` | `test_a_dry_run_says_a_full_reset_without_an_instance_id_would_refuse` |
| P-16 | M1 | `src/probos/__main__.py` | `if tier >= 3:  # AD-1341 S6: what a --full reset deletes from Ship's Records is kept first, as one checked file` | `if tier >= 2:` | `test_a_tier2_reset_keeps_ship_records_and_takes_no_snapshot` |
| P-17 | M1 | `src/probos/__main__.py` | `unlisted = [path for path in result.paths if path.endswith(".md") and path not in listed]` | `unlisted = []` | `test_a_full_reset_keeps_ship_records_as_one_checked_bag_before_it_deletes_them` |
| P-18 | M1 | `src/probos/knowledge/archive_ledger.py` | `"UPDATE archive_snapshots SET erased_at = ?, erase_reason = ? WHERE id = ? AND erased_at IS NULL"` | `"UPDATE archive_snapshots SET erased_at = ?, erase_reason = ? WHERE id = ?"` | `test_the_ledger_records_a_snapshot_without_its_content_and_marks_its_erasure_once` |
| P-19 | M1 | `src/probos/knowledge/archive_ledger.py` | `if version != ARCHIVE_SCHEMA_VERSION:` | `if False:` | `test_the_ledger_opens_only_an_archive_the_store_has_brought_to_its_schema` |
| P-20 | M1 | `src/probos/knowledge/archive_ledger.py` | `if snapshot_id > _SQLITE_MAX_ROWID:` | `if False:` | `test_the_ledger_records_a_snapshot_without_its_content_and_marks_its_erasure_once` |
| P-21 | M1 | `src/probos/knowledge/archive_store.py` | `CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_snapshots_path ON archive_snapshots(relative_path);` | `CREATE INDEX IF NOT EXISTS idx_archive_snapshots_path ON archive_snapshots(relative_path);` | `test_the_ledger_records_a_snapshot_without_its_content_and_marks_its_erasure_once` |
| P-22 | M1 | `src/probos/__main__.py` | `also = " The Ship's Records snapshot is skipped with it." if tier >= 3 else ""  # AD-1341 S6` | `also = ""` | `test_skip_promotion_skips_the_snapshot_with_it_and_says_so` |
| P-23 | M1 | `src/probos/__main__.py` | `_show_snapshot_plan(config, data_dir, console)  # AD-1341 S6: what a --full reset would keep` | `pass` | `test_a_dry_run_shows_the_snapshot_a_full_reset_would_keep_and_writes_nothing` |
| P-24 | M1 | `src/probos/__main__.py` | `return "(present)" if (directory / entry.relative_path).is_file() else "(missing)"` | `return "(missing)"` | `test_the_captain_lists_and_erases_a_snapshot_with_the_marker_first` |
| D-1 | M2 | `src/probos/knowledge/nature_description.py` | `printable = "".join(" " if unicodedata.category(char)[0] == "C" else char for char in value)` | `printable = value` | `test_text_from_the_store_is_one_line_without_control_or_format_characters` |
| D-2 | M2 | `src/probos/knowledge/nature_description.py` | `return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."` | `return text` | `test_text_from_the_store_is_one_line_without_control_or_format_characters` |
| D-3 | M2 | `src/probos/knowledge/nature_description.py` | `state = "an anti-pattern" if negative else ("active" if active else "retired")` | `state = "active"` | `test_a_reset_archives_one_description_of_what_this_crew_developed_never_the_procedures` |
| D-4 | M2 | `src/probos/knowledge/nature_description.py` | `if len("\n".join(lines)) + 1 + len(line) > budget:` | `if False:` | `test_a_description_at_its_bound_reaches_a_later_crew_whole_through_the_oracle_tool` |
| D-5 | M2 | `src/probos/knowledge/nature_description.py` | `if developed > listed:` | `if False:` | `test_a_description_at_its_bound_reaches_a_later_crew_whole_through_the_oracle_tool` |
| D-6 | M2 | `src/probos/knowledge/nature_description.py` | `"WHERE created_at >= ? ORDER BY total_completions DESC, created_at, id LIMIT ?"` | `"WHERE created_at >= ? ORDER BY created_at, id LIMIT ?"` | `test_a_reset_archives_one_description_of_what_this_crew_developed_never_the_procedures` |
| D-7 | M2 | `src/probos/knowledge/nature_description.py` | `if not db_path.is_file():  # no procedure store: this generation developed nothing to describe` | `if False:` | `test_nothing_to_describe_archives_nothing_and_creates_no_store` |
| D-8 | M2 | `src/probos/knowledge/archive_promotion.py` | `or not record.source_ref.startswith(NATURE_DESCRIPTION_PREFIX)` | `or False` | `test_only_a_nature_description_without_episodes_is_promoted_as_one` |
| D-9 | M2 | `src/probos/knowledge/archive_promotion.py` | `or record.source_episode_ids` | `or False` | `test_only_a_nature_description_without_episodes_is_promoted_as_one` |
| D-10 | M2 | `src/probos/__main__.py` | `notes.insert(0, await _describe_nature(archive, nature))  # AD-1341 S6 A2: archived after the snapshot (B-F2)` | `pass` | `test_a_reset_archives_one_description_of_what_this_crew_developed_never_the_procedures` |
| D-11 | M2 | `src/probos/__main__.py` | `if nature is not None:  # AD-1341 S6: the next reset would archive it too; probos archive veto keeps it out` | `if False:` | `test_the_captain_reviews_and_vetoes_a_description_before_the_reset` |
| D-12 | M2 | `src/probos/__main__.py` | `if record is None and source_ref.startswith(NATURE_DESCRIPTION_PREFIX):  # AD-1341 S6: this generation's description` | `if False:` | `test_the_captain_reviews_and_vetoes_a_description_before_the_reset` |
| D-13 | M2 | `src/probos/__main__.py` | `if nature is not None:  # AD-1341 S6: the Captain reads what a later crew would` | `if False:` | `test_the_dry_run_shows_the_description_the_reset_would_archive` |
| K-1 | M3 | `src/probos/__main__.py` | `if clean_slate and tier < 2:  # AD-1341 S6: --soft keeps the crew, so there is no new crew to start clean` | `if False:` | `test_a_clean_slate_that_does_not_apply_or_cannot_be_recorded_changes_nothing` |
| K-2 | M3 | `src/probos/__main__.py` | `if clean_slate and not config.archive.enabled:  # AD-1341 S6: a clean slate is never unrecorded` | `if False:` | `test_a_clean_slate_that_does_not_apply_or_cannot_be_recorded_changes_nothing` |
| K-3 | M3 | `src/probos/__main__.py` | `if clean_slate and not _clear_nature(config, tier, data_dir, console):` | `if False:` | `test_a_clean_slate_describes_records_and_clears_nature_and_touches_nothing_else` |
| K-4 | M3 | `src/probos/__main__.py` | `if is_link_status(status):  # AD-1341 S6: never followed out of the data directory` | `if False:` | `test_a_link_or_a_file_at_the_procedures_name_is_refused_before_anything_is_written` |
| K-5 | M3 | `src/probos/__main__.py` | `count = asyncio.run(_record_nature_clearance(config, data_dir, tier))  # AD-1341 S6: the marker first` | `count = 0` | `test_a_clean_slate_describes_records_and_clears_nature_and_touches_nothing_else`, `test_a_clean_slate_whose_marker_cannot_be_written_deletes_nothing` |
| K-6 | M3 | `src/probos/__main__.py` | `return False  # AD-1341 S6: the deletion is recorded and unfinished; the reset refuses before its tier loop` | `return True` | `test_an_interrupted_clean_slate_is_finished_by_running_it_again` |
| K-7 | M3 | `src/probos/__main__.py` | `cleared = (f"{_NATURE_DIR}/",) if (data_dir / _NATURE_DIR).exists() else ()` | `cleared = ()` | `test_a_clean_slate_describes_records_and_clears_nature_and_touches_nothing_else` |
| K-8 | M3 | `src/probos/__main__.py` | `table.add_row("\n[bold]Nature (--clean-slate)[/bold]", "", "")` | `pass` | `test_the_dry_run_and_the_confirmation_name_what_a_clean_slate_clears` |
| K-9 | M3 | `src/probos/__main__.py` | `kept = [] if clean_slate else [(f"{_NATURE_DIR}/", "Cognitive JIT procedures: nature, kept by design", "")]` | `kept = []` | `test_the_dry_run_and_the_confirmation_name_what_a_clean_slate_clears` |
| K-10 | M3 | `src/probos/__main__.py` | `console.print("  Nature kept: procedures/ (Cognitive JIT procedures)")` | `pass` | `test_without_clean_slate_nature_persists_at_every_tier` |
| K-11 | M3 | `src/probos/knowledge/archive_ledger.py` | `if type(self.reset_tier) is not int or self.reset_tier not in (2, 3):  # AD-1341 S6: tier 1 keeps the crew` | `if type(self.reset_tier) is not int:` | `test_a_clean_slate_marker_holds_only_what_it_may` |
| K-12 | M3 | `src/probos/knowledge/archive_ledger.py` | `if type(self.procedure_count) is not int or self.procedure_count < -1:` | `if type(self.procedure_count) is not int:` | `test_a_clean_slate_marker_holds_only_what_it_may` |
| P-25 | M1 | `src/probos/knowledge/records_snapshot.py` | `except FileNotFoundError:  # only absence is None (A2, A-F1)` | `except OSError:` | `test_a_ship_records_root_that_cannot_be_inspected_refuses` |
| P-26 | M1 | `src/probos/knowledge/records_snapshot.py` | `if is_link_status(root_status):  # the root itself is never followed either (A2)` | `if False:` | `test_a_ship_records_root_that_is_a_link_is_never_followed` |
| P-27 | M1 | `src/probos/knowledge/records_snapshot.py` | `if is_link_or_junction(directory):  # A2: written only into the snapshots directory itself` | `if False:` | `test_a_snapshot_is_written_only_into_the_snapshots_directory_itself` |
| P-28 | M1 | `src/probos/__main__.py` | `if is_link_or_junction(directory):  # AD-1341 S6 A2: a snapshot is never written through a link` | `if False:` | `test_a_snapshot_is_written_only_into_the_snapshots_directory_itself` |
| P-29 | M1 | `src/probos/__main__.py` | `if snapshots == resolved or snapshots.startswith(within) or resolved.startswith(snapshots + os.sep):` | `if False:` | `test_a_snapshot_is_written_only_into_the_snapshots_directory_itself` |
| P-30 | M1 | `src/probos/__main__.py` | `problem = _snapshot_file_problem(_snapshots_dir(config), entry.relative_path)  # A2: before the marker` | `problem = ""` | `test_an_erasure_deletes_only_a_regular_file_inside_the_snapshots_directory` |
| P-31 | M1 | `src/probos/__main__.py` | `if status is not None and not stat.S_ISREG(status.st_mode):  # a directory, a link or a special file there` | `if False:` | `test_an_erasure_deletes_only_a_regular_file_inside_the_snapshots_directory` |
| P-32 | M1 | `src/probos/__main__.py` | `if is_link_or_junction(component):  # AD-1341 S6 A2: an erasure never follows one` | `if False:` | `test_an_erasure_deletes_only_a_regular_file_inside_the_snapshots_directory` |
| P-33 | M1 | `src/probos/knowledge/records_snapshot.py` | `for name in expected[len(plan.files):]:  # A2: the tag files too, read whole, so zipfile checks each CRC` | `for name in ():` | `test_a_tag_file_that_reads_back_wrong_refuses_the_snapshot` |
| P-34 | M1 | `src/probos/__main__.py` | `if refusal:  # AD-1341 S6 A4: a reset that would refuse does nothing, so its dry run reads nothing more` | `if False:` | `test_a_dry_run_says_a_full_reset_without_an_instance_id_would_refuse`, `test_a_refused_dry_run_reads_nothing_through_the_procedures_link` |
| P-35 | M1 | `src/probos/__main__.py` | `console.print(f"    {refusal}", markup=False, emoji=False)` | `pass` | `test_a_dry_run_says_a_full_reset_without_an_instance_id_would_refuse`, `test_a_dry_run_shows_the_snapshot_a_full_reset_would_keep_and_writes_nothing` |
| P-36 | M1 | `src/probos/__main__.py` | `if refusal:  # AD-1341 S6 A2: before the confirmation, the pidfile and the promotion, so nothing is written` | `if False:` | `test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing` |
| D-14 | M2 | `src/probos/knowledge/archive_promotion.py` | `if state.outcome is PromotionOutcome.CREATED and state.entry_ids:  # A2 (B-F2): one per generation` | `if False:` | `test_one_description_per_generation_whatever_its_content`, `test_a_retried_reset_keeps_one_description_per_generation` |
| D-15 | M2 | `src/probos/__main__.py` | `for line in nature.record.content.splitlines():  # AD-1341 S6 A2 (B-F1): the Captain reads the text itself` | `for line in ():` | `test_the_captain_reviews_and_vetoes_a_description_before_the_reset` |
| D-16 | M2 | `src/probos/__main__.py` | `if record.source_kind is SourceKind.NATURE_DESCRIPTION:  # AD-1341 S6 A2 (B-F1): the text it keeps out` | `if False:` | `test_the_captain_reviews_and_vetoes_a_description_before_the_reset` |
| K-13 | M3 | `src/probos/__main__.py` | `if not stat.S_ISDIR(status.st_mode):  # AD-1341 S6 A2: a file at that name is refused too` | `if False:` | `test_a_link_or_a_file_at_the_procedures_name_is_refused_before_anything_is_written` |
| K-14 | M3 | `src/probos/__main__.py` | `if clean_slate:  # AD-1341 S6 A2: before the promotion reads the procedure store through it (B-F3, C-F2)` | `if False:` | `test_a_link_or_a_file_at_the_procedures_name_is_refused_before_anything_is_written` |
| K-15 | M3 | `src/probos/__main__.py` | `problem = _nature_dir_problem(data_dir)  # AD-1341 S6 A2: asked again where it deletes` | `problem = ""` | `test_the_clearance_refuses_a_link_or_a_file_again_where_it_deletes` |
| K-16 | M3 | `src/probos/__main__.py` | `if clean_slate:  # AD-1341 S6 A2: --clean-slate deletes the procedure store's directory too (C-F1)` | `if False:` | `test_an_archive_inside_the_procedure_store_refuses_a_clean_slate` |
| K-17 | M3 | `src/probos/__main__.py` | `if closing is not None and not _close_generation(config, closing, console):` | `if False:` | `test_an_interrupted_clean_slate_is_finished_by_running_it_again`, `test_a_skipped_promotion_is_closed_only_after_its_clean_slate` |
| K-18 | M3 | `src/probos/__main__.py` | `return False  # AD-1341 S6 A2: not closed; the reset refuses before its tier loop` | `return True` | `test_a_retried_reset_keeps_one_description_per_generation` |
| P-37 | M1 | `src/probos/knowledge/records_snapshot.py` | `return stat.S_ISLNK(status.st_mode) or reparse_tag == _IO_REPARSE_TAG_MOUNT_POINT  # A4: no Windows-only name` | `return stat.S_ISLNK(status.st_mode) or reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT` | `test_a_status_is_judged_by_its_mode_and_only_a_junction_s_tag`, `test_a_full_reset_its_dry_run_and_an_erasure_need_no_windows_only_name`, `test_a_clean_slate_needs_no_windows_only_name` |
| P-38 | M1 | `src/probos/knowledge/records_snapshot.py` | `return stat.S_ISLNK(status.st_mode) or reparse_tag == _IO_REPARSE_TAG_MOUNT_POINT  # A4: no Windows-only name` | `return stat.S_ISLNK(status.st_mode) or reparse_tag != 0` | `test_a_status_is_judged_by_its_mode_and_only_a_junction_s_tag` |
| P-39 | M1 | `src/probos/knowledge/records_snapshot.py` | `return stat.S_ISLNK(status.st_mode) or reparse_tag == _IO_REPARSE_TAG_MOUNT_POINT  # A4: no Windows-only name` | `return stat.S_ISLNK(status.st_mode)` | `test_a_status_is_judged_by_its_mode_and_only_a_junction_s_tag` |
| P-40 | M1 | `src/probos/knowledge/records_snapshot.py` | `return alias if os.path.samestat(final_status, alias_status) else None  # one file under two names` | `return alias` | `test_an_erasure_leaves_a_temporary_name_that_is_another_file` |
| P-41 | M1 | `src/probos/__main__.py` | `alias = retained_alias(path)  # AD-1341 S6 A4 (A-R2-F2): the temporary name publish could not remove` | `alias = None` | `test_an_erasure_removes_the_temporary_name_a_publish_could_not` |
| P-42 | M1 | `src/probos/__main__.py` | `for name in (*([alias] if alias is not None else []), path):  # A4: the alias first, so a rerun still finds it` | `for name in (path, *([alias] if alias is not None else [])):` | `test_an_erasure_removes_the_temporary_name_a_publish_could_not` |
| P-43 | M1 | `src/probos/__main__.py` | `if is_snapshot_relative_path(entry.relative_path) and os.path.lexists(directory / entry.relative_path):` | `if False:` | `test_an_erasure_removes_the_temporary_name_a_publish_could_not` |
| P-44 | M1 | `src/probos/knowledge/records_snapshot.py` | `if not (final_status.st_ino and alias_status.st_ino):  # A5 (A-R3-F1): an index of 0 identifies no file` | `if False:` | `test_an_erasure_refuses_a_temporary_name_whose_identity_cannot_be_shown` |
| P-45 | M1 | `src/probos/__main__.py` | `retained_alias(path)  # AD-1341 S6 A5 (A-R3-F1): a temporary name of unknown identity refuses before the marker` | `pass` | `test_an_erasure_refuses_a_temporary_name_whose_identity_cannot_be_shown` |
| K-19 | M3 | `src/probos/__main__.py` | `f"Ship's Archive promotion skipped; the reason will be recorded with the generation's close: "` | `f"Ship's Archive promotion skipped; the reason is recorded: "` | `test_a_skipped_promotion_is_closed_only_after_its_clean_slate` |

The heading's count is the row count: 45 for M1 (P-1 to P-45), 16 for M2 (D-1 to D-16), 19 for M3 (K-1 to K-19), 80 in all; the orchestrator's census recounts it. **A4:** P-34 is rewritten for A4's dry-run branch (A2's line is gone) and is killed by X14b (the tier table and "would be kept" print) and C14 (`procedures.db` opened, `procedures/` sized). P-37 to P-39 mutate one line; restore between them. P-37 is the round-2 defect itself and is killed on Windows because X18, X19 and C15 swap `records_snapshot`'s `stat` for a POSIX build's (X18's source scan sees it too). Only X18's cloud-placeholder status kills P-38, and only X18's junction-shaped status kills P-39 (on Windows also X7c, X16 and C7[junction]). Only X17b kills P-40 (another file at the temporary name, which only file identity refuses). X17 kills P-41, P-42 and P-43; for P-42, with the final name first, the denied alias removal leaves no final name to find the alias by, so the rerun leaves it. K-19 is killed by C13's message assertion. No row for `retained_alias`'s absence guard (A5: its mutant reaches `None.st_ino`, an `AttributeError` raised in the erasure's preflight, before the marker, which X12's and X19's erasures see as exit 1) or the refusal branch's `return 0` (its fall-through is P-34's behaviour). **A5:** only X17c kills P-44 and P-45 (every index reported as 0, another file at the temporary name). With P-44 the erasure removes that file and exits 0. With P-45 the check after the marker refuses (exit 1 through `except (OSError, SnapshotRefused)`), but the row is marked and the output lacks "Nothing was erased.". X17b keeps P-40's data: real, unequal indices pass P-44's guard and reach `samestat` (R41). No row for the clause after the marker: it differs from the wrapper's `except Exception` only in its message, and it is reached only when the name changes after the preflight (R28). **A2:**
- P-15 is killed by X14b's message. With the line mutated, an empty instance id still refuses through `snapshot_relative_path`, with another message, so X5's exit code alone cannot kill it.
- P-27 and K-15 are the checks repeated behind the preflight; only their direct tests (X16's `prepare` part, C11) reach them.
- P-28 survives X16's first reset part only if `prepare_snapshot`'s own check refuses, which happens after the archive was opened; X16 asserts that no archive file exists, so the row is killed.
- K-4 is killed on Windows, where a junction's `lstat` is a directory. On POSIX the next line refuses a symlink as "not a directory", so there it is outcome-equivalent.
- K-14's junction case kills it; its file case is outcome-equivalent, because no description is read through a file.
- **A3:** P-8 is killed only by X3's `member-extra` case. Since A2 the tag read-back (P-33's line) opens every listed member by name, so a missing member (`member-missing`) refuses there too (`KeyError`) and no longer reaches the member-list check. A member the bag does not list is opened by neither loop. `member-missing` stays in X3, with no row of its own.
- The baseline run is the three new files and `tests/test_ad1341_s3_veto_store.py`: 149 cases by analysis (A3: 138 and `member-extra`; A4: 139 and nine, X17, X17b, X18, X19 ×3, C14 ×2 and C15; A5: 148 and X17c). P-3 and P-4 mutate the same line; restore between them. D-6 is killed only because N1 creates its anti-pattern first (p-3 at `_B + 30.0`). When the creation order equals the completions order, the mutated `ORDER BY` lists the same lines; N1's premise assertion keeps the data from drifting back (A1). P-18 names the ledger test alone. `_erase_snapshot` marks only when `entry.erased_at is None`, so X12's rerun never reaches the `UPDATE`. `AND erased_at IS NULL` is the ledger's own guard: it keeps the first reason when two `erase-snapshot` commands both read the row unmarked, for example while one waits at its confirmation prompt (A1). K-3 leaves nature in place, so C1's `not (data_dir / "procedures").exists()` fails. K-5 skips the marker: C1's `nature_clearances` row is missing, and C5 (which makes the marker fail) deletes nature, so `procedures/` is gone where C5 expects it.

## 11. Verified Against Codebase (2026-10-27, on `4b3101f3`: the S5 repair candidate, S5 Amendment A3 in)

§0 to §7 were drafted on `4c2ebdc7` by the first run, with its own greps (§0's evidence column). This run re-verified, on `4b3101f3`, every SEARCH anchor in §7 that targets base text, the names §7 calls, and the censuses §7 must keep. Each grep below was run with the Grep tool on this worktree on 2026-10-27.

**What S5 changed since the draft's base:** `git diff --stat 4c2ebdc7 HEAD` lists `after_action.py`, `knowledge/archive_promotion.py` (+30), two S5 tests and trackers. `git diff --stat 391796cb HEAD` lists no change to `__main__.py`, `records_store.py`, `procedure_store.py`, `sqlite_factory.py` or `store-baseline.yaml`; in `archive_store.py` one line (`:104`) and in `tests/test_ad1341_s1_archive_store.py` the closed-set assertion.

```
grep -n "manager reads ``entry_ids_citing``|episode it would erase" src/probos/knowledge/archive_store.py
  16-17   (7.3 pair 1; one occurrence)
grep -n 'AFTER_ACTION_REPORT = "after_action"' src/probos/knowledge/archive_store.py
  104     (7.7; S5's line)
grep -n "idx_archive_vetoes_source ON archive_vetoes" src/probos/knowledge/archive_store.py
  280-281 (7.3 pair 2; followed by the closing """)
grep -n "executescript|user_version|ARCHIVE_SCHEMA_VERSION =" src/probos/knowledge/archive_store.py
  83 ARCHIVE_SCHEMA_VERSION = 1; 471-479 version in (0, 1) then executescript(_SCHEMA) on every open; 486 user_version written
  (so an existing v1 archive gains both new tables at its next open)
grep -n "ARCHIVE_REASON_MAX_CHARS" src/probos/knowledge/archive_store.py        90 = 500
grep -n "class PromotionRecord" src/probos/knowledge/archive_store.py            151
grep -n "vetoed=tuple(vetoed),|^class PendingSource" src/probos/knowledge/archive_promotion.py
  451-456 (7.8's anchor: `vetoed=tuple(vetoed),` + `)` + two blanks + `@dataclass(frozen=True)` + `class PendingSource:`; the other `vetoed=tuple(vetoed), waiting=...` at 593 is a different line)
grep -n "source_state" src/probos/knowledge/archive_promotion.py                 323, 479, 573 (the review's reads)
grep -n "^from __future__" src/probos/knowledge/archive_promotion.py             25
- module: probos.knowledge.archive_store … docs/development/store-baseline.yaml  121-126 (7.4)
grep (src/probos/__main__.py), each the anchor's first line, each once unless noted:
  68-69  the annotation-only imports (7.5 pair 1)
  2795   def _show_confirmation_prompt(        2852 def _show_dry_run(
  2815-2819 / 2872-2875  `for name, purpose, size in items:` twice; the 4-line blocks differ (`# What will be preserved` vs `preserved_items = []`), so 7.17 pairs 2 and 5 each match once
  2825-2827 / 2881-2882  7.17 pairs 3 and 6 (distinct blocks)
  2905   def _cmd_reset (pairs 8-12 of 7.17 are inside it; the summary 3149-3150 too)
  2908   the exit-code docstring (7.17 pair 7)    2928-2931 `{problem}` / return 2 / blank / `# Load config ...` (7.17 pair 8)
  2942   `# AD-1341 S1 A4 (F3): refuse a reset ...` (7.17 pair 9)
  2975-2978 the dry-run block (7.5 pair 2, 7.17 pair 10)     3007-3010 refused / `# ── Execute reset ──` (7.17 pair 11)
  3297, 3305-3307, 3319, 3323 (7.5 pairs 3-6)   3336, 3359 (7.5 pairs 7-8)   3341, 3352 (7.10 pairs 3-4)
  3377 (7.5 pair 9)   3446, 3454 (7.10 pairs 5-6)   3526-3527, 3533 (7.10 pairs 7-8; inside `async def _veto_pending_source`, 3522)
  3567 def _force_remove_readonly (7.5 pair 10; 7.17 pair 13 anchors on M1's re-emitted copy: once after M1)
  3877 the --skip-promotion help (7.17 pair 14)   3912 archive_veto --data-dir (7.5 pair 11)
  23 import shutil; 51 from rich.table import Table; 2684 def _get_file_size; 3166 _UNATTRIBUTED_TIMELINE; 3180 def _read_instance_id;
  3192-3198 def _reset_records_store (RecordsStore(config.records.model_copy(update={"repo_path": ...}), ontology=None)); 3201 def _configured_archive_store;
  3247-3274 _promote_before_reset (asyncio.run of _promote_into_archive; any exception refuses); 3277-3320 _promote_into_archive(config, tier, data_dir, timeline_id, skip_reason)
  3867 reset_parser = subparsers.add_parser("reset", ...)
grep -n "def connect|read_only|mode=ro" src/probos/storage/sqlite_factory.py     18 connect(self, db_path, *, read_only=False); 36-37 mode=ro URI
grep -n "class DatabaseConnection|class ConnectionFactory" src/probos/protocols.py  325, 362
grep -n "def generate_ship_did" src/probos/identity.py                            103
grep -n "def resolve_archive_db_path" src/probos/config.py                        2631
grep -n "EXIT_NOTE_TIMELINE_MAX_CHARS" src/probos/knowledge/lessons.py            40 (= 64)
grep -n "_MAX_ENTRY_CHARS = " src/probos/tools/oracle_query_tool.py              71 (= 1200)
grep -n "def __init__(self, config|list_entries|rel_path = " src/probos/knowledge/records_store.py
  214 (config, ontology=None); 1001-1057 list_entries: rglob("*.md"), rel_path "/"-separated (1031), `_archived/` skipped (1033), unreadable or undecodable skipped (1038-1045)
grep -n "requires-python" pyproject.toml                                         9 ">=3.12" (Path.is_junction, DirEntry.is_junction)
grep -n "is_junction" src/probos/cognitive/profile_components.py                 47, 87 (the precedent)
grep -n "SRP_MAX_BODY_LINES|SRP_MAX_DIRECT_METHODS|triggers.append" scripts/check_architecture_principles.py  187-188, 566-569
grep -n "__main__|archive_store|archive_promotion" docs/development/architecture-baseline.yaml  34-38: one row, probos.__main__::_cmd_reset sqlite3.connect count 2 (S6 adds no sqlite3.connect)
Censuses §7 must keep (tests/):
  test_ad1341_s1_promotion.py:430-437   only knowledge/archive_promotion.py names promote_entry        (holds)
  test_ad1341_s3_veto_store.py:515-517  only knowledge/archive_promotion.py names source_state       (held after this run's fix to 7.8/7.10)
  test_ad1341_s3_review_cli.py:256      only __main__.py names veto_source                          (holds)
  test_ad1341_s3_erasure_cascade.py:303-305; test_ad1341_s1_reset_and_erase.py:601 (erase_entry, record_generation: __main__.py)  (hold)
  test_ad1341_s4_exit_note_erasure.py:321-322; test_ad1341_s5_continuous_promotion.py:448   (unaffected)
grep -n "^# ProbOS Progress" PROGRESS.md      1  (S5's entry at 3)
grep -n "^### (AD-1341|Explicit delegation models)" DECISIONS.md   575 S1, 748 S2, 808 S3, 819 S4, 845 S5, 855 Explicit delegation models
RFC 8493 (rfc-editor.org, fetched 2026-10-27): 2.1.1 bagit.txt is exactly two lines; 2.1.3 LF, CR, CRLF and "%" (and only those) MUST be percent-encoded in a manifest path; 2.2.2 Payload-Oxum is "OctetCount.StreamCount".
```

## A2 verification (2026-10-27, on `f9afeb59`, tree `61e4fce9`)

Each anchor was read on the candidate with the Read and Grep tools; the contract's code is blob-equal to it.

```
src/probos/__main__.py
  64-74      TYPE_CHECKING imports; line 72 the archive_store names (7.17 pair 0)
  2987-2996  S1 A4's comment, the overlap call and its two-line message (7.5 pair 1a; 7.17 pair 9)
  3019-3030  the dry run and the confirmation (S1 text under M3; 7.5 pair 2, 7.17 pairs 10 and 10a)
  3049-3060  promote_first, the refusal, the clean slate (7.17 pair 11)
  3271-3299  _archive_reset_overlap, S1's text (7.5 pair 3)
  3302-3329  _promote_before_reset, S1's text (7.17 pair 12c)
  3332-3351, 3358  _promote_into_archive's head and no-id branch, S1's text (7.17 pair 12d); 3352-3357 were M1's pair 3, removed by A2
  3362-3385  the skip and the close (7.17 pairs 12e, 12f)
  3407-3415  _describe_nature (7.10 pair 2); 3456-3460 _snapshot_plan (7.5 pair 6)
  3561-3563  _show_promotion_plan's signature; 3606-3610 the dry run's snapshot plan (7.5 pair 8)
  3708-3711  pending's nature line (7.10 pair 6); 3782-3783 the veto's imports (pair 7); 3799-3800 its confirmation (pair 9)
  3912-3930  _erase_snapshot (7.5 pair 10); 3933-3992 _clear_nature, _record_nature_clearance (7.17 pair 13)
src/probos/knowledge/records_snapshot.py  15-21 docstring; 27-35 imports; 100-104 publish; 116-133 the plan's head; 174-178 prepare; 244-254 _verify_bag
src/probos/knowledge/archive_promotion.py  34-41 imports PromotionOutcome and SourceState already; 475 promote_entry in promote_nature_description
src/probos/knowledge/archive_store.py  114-121 PromotionOutcome; 139-149 SourceState; 534-572 promote_entry, keyed (kind, ref, sha256); 666-687 source_state: entry_ids for any content
src/probos/storage/sqlite_factory.py  25-34 mode=ro's documented WAL side effect
src/probos/cognitive/procedure_store.py  211 PRAGMA journal_mode=WAL
src/probos/security/file_access.py  767-783 publish_file, "Atomic, no-replacement publication" by os.link; 505-513 is_reparse_point
src/probos/infrastructure/backup.py  739-746 os.link with a logged copy fallback (AD-1265)
tests/test_layer_boundaries.py  49 knowledge may import substrate only
tests/test_ad1341_s1_reset_and_erase.py  751-788 the overlap cases ("outside" puts the archive at tmp_path/archive.db, its snapshots outside data_dir); 785 asserts the first message line only
logs/ad1341s6r1/review-ad1341s6-{a,b,c}-r1.md  the findings, their locations and their executed evidence
```

## Absence Verified (A2, 2026-10-27)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A2-AV1 | No test calls `_promote_into_archive`, `_promote_before_reset` or `_archive_reset_overlap`, or asserts the overlap message's second line | Grep `_promote_into_archive\|_promote_before_reset\|record_generation\|_archive_reset_overlap\|archive.db_path is inside\|is inside what this reset` in `tests/` | `record_generation` only in store tests and censuses; `test_ad1341_s1_reset_and_erase.py:785` (the first line) | yes |
| A2-AV2 | No reset test asserts the promotion's failure line or the refusal lines A2 adds beside | Grep `promotion failed\|refused before deleting anything\|refused before its tier loop` in `tests/` | `test_ad1296_working_dir_ownership.py:685` (AD-1296's own), `test_ad1341_s5_continuous_promotion.py:450` (S5's log) | yes |
| A2-AV3 | No test pins the skip or no-id promotion messages | Grep `the reason is recorded\|No instance id and nothing to promote\|promoted, .* already archived` in `tests/` | none | yes |
| A2-AV4 | `_show_promotion_plan`, `_promote_before_reset` and `_clear_nature` each have one caller, `_cmd_reset` | Grep the names in the repository | `__main__.py:3023`, `:3051`, `:3056`, and the contracts | yes |
| A2-AV5 | No `src` module reads `st_reparse_tag` or `IO_REPARSE_TAG` yet | Grep `IO_REPARSE_TAG\|st_reparse_tag` in `*.py` | none (`file_access.py` uses `st_file_attributes & 0x400`) | yes |

## A3 verification (2026-10-27, on `47568aa7`, tree `d3bd66a8`)

```
grep -n "namelist|_digest(bag_zip.open|for name in expected" src/probos/knowledge/records_snapshot.py
  297: if bag_zip.namelist() != expected:                     (P-8)
  300: the payload loop opens each listed payload member by name
  302-303: A2's tag loop opens each listed tag member by name (P-33)
grep -n "member-missing|_no_bag_info" tests/test_ad1341_s6_records_snapshot.py
  272, 311-316: the one fault that changes the bag's members; it leaves out bag-info.txt, which :303 opens (KeyError)
logs/ad1341s6a3/evidence-ad1341s6census-d.txt
  11: P-8 SURVIVED ... CLAIMED-NOT-FAILING [43 passed]
  61: P-33 KILLED by X8b [1 failed, 42 passed]: X8b's names are intact, so P-8's check is not what kills it
src/probos/__main__.py:3582-3597: prepare_snapshot, then record_snapshot, then publish: a bag that passes _verify_bag completes the reset
```

## Absence Verified (A3, 2026-10-27)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A3-AV1 | No S6 test writes a bag member `_verify_bag` does not expect | Grep `writestr\|_write_text\|ZipFile\(\|namelist` in `tests/test_ad1341_s6_*.py` | the records-snapshot file only: 241-243 (reads), 281 and 316 (`member-missing` omits one), 437-438 (asserts the list), 770 (X8b flips a byte in place) | yes |
| A3-AV2 | Nothing but `_verify_bag` reads a bag back | Grep `zipfile\|prepare_snapshot\|_verify_bag` in `src/probos` | `records_snapshot.py` only; `__main__.py:3574, 3582` import and call `prepare_snapshot` | yes |
| A3-AV3 | No test counts X3's cases or names its ids | Grep `_FAULTS\b` in `tests/` | the S6 file 270, 275, 324, 340; `_WALK_FAULTS` (S4) and `_RECORDING_FAULTS` (BF-939) are other names | yes |

## A4 verification (2026-10-27, on `2a1b6319`, tree `94a75834`)

Each anchor was read on the candidate with the Read and Grep tools; the external sources were fetched.

```
src/probos/knowledge/records_snapshot.py
  105-122    publish: os.link, then _remove_quietly(self.temp_path), logged and never raised (A-R2-F2)
  141-161    lstat_or_none; is_link_status: 154 getattr(status, "st_reparse_tag", 0), 155 stat.IO_REPARSE_TAG_MOUNT_POINT unconditionally (A-R2-F1); is_link_or_junction
  187        entry.is_symlink() or entry.is_junction()
  227        temp = final.with_name(f".{final.name}.partial"): the one builder of the name
  351-356    _remove_quietly
src/probos/__main__.py
  2689-2704  _get_file_size: rglob through the given path; 2804-2811 _nature_rows sizes data_dir/procedures (R2-B1)
  3022       the preflight; 3025-3033 the dry run: _show_dry_run, _show_promotion_plan(..., snapshot=not refusal), then the refusal; 3034-3037 the executing refusal
  3072-3078  the clearance, then _close_generation; 3362 _promote_before_reset prints the message; 3391-3397 the skip's "the reason is recorded" (C-R2-F2)
  3426-3435  _nature_record -> nature_description_record(..., _open_read_only, ...); 3659 the dry run's call
  3497-3533  _reset_preflight: 3509 import, 3511-3514 the clean slate's check first, 3529 is_link_or_junction
  3634-3684  _show_promotion_plan(..., snapshot=True); 3682-3683 the snapshot plan
  3934-3942  _snapshot_state; 3982-4014 _erase_snapshot, 4007-4012 its one unlink; 4017-4036 _snapshot_file_problem
  4099-4121  _nature_dir_problem: 4108 import, 4117 is_link_status
src/probos/knowledge/nature_description.py  38 PROCEDURES_DB; 162, 186 is_file before any open
tests/test_ad1341_s6_records_snapshot.py  88-91 _snapshot_files (a .partial included); 158-177 _reset, _archive, _erasures; 180-190 _link_dir; 583-602 X12's Path.unlink double; 839-852 X14b
tests/test_ad1341_s6_clean_slate.py  85-100 _nature; 119-139 _reset, _link_dir; 295-304 _odd_procedures; 386-411 C13
pyproject.toml  9 requires-python ">=3.12"; 180-196 pytest options, no filterwarnings
.github/workflows/ci.yml  17, 96, 123 ubuntu-latest; 47, 110, 139 Python 3.12; no container
CPython v3.12.13 Modules/_stat.c  IO_REPARSE_TAG_SYMLINK, _MOUNT_POINT, _APPEXECLINK added inside #ifdef MS_WINDOWS
CPython v3.12.13 Lib/ntpath.py  isjunction: return bool(st.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT), outside its try
MS-FSCC 2.1.2.1  IO_REPARSE_TAG_MOUNT_POINT 0xA0000003 (a junction and a volume mount point); IO_REPARSE_TAG_SYMLINK 0xA000000C
logs/ad1341s6r2/review-ad1341s6-{a,b,c}-r2.md  the findings and their executed evidence
```

## Absence Verified (A4, 2026-10-27)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A4-AV1 | No S6 production line but `records_snapshot.py:155` names a platform-only name | Grep `IO_REPARSE\|st_reparse_tag\|st_file_attributes\|FILE_ATTRIBUTE\|_winapi\|msvcrt\|ctypes\|sys\.platform\|os\.name\b\|normcase\|os\.link\|winerror` in `src/probos/knowledge` and `src/probos/__main__.py`; `git diff 7cb0b212 2a1b6319 -- src/probos/__main__.py \| grep -n "sys.platform\|os.name\|normcase\|_winapi\|msvcrt\|IO_REPARSE\|st_file_attributes"` | `knowledge`: `records_snapshot.py:108` (docstring), `:114` (`os.link`), `:154`, `:155`; `__main__.py`: 38, 440, 1565, 2479, 2548, 2632, 3307, 3308, 3323, 4530, of which the S6 diff adds only 3308 (`normcase`, as S1's 3307 and 3323) | yes |
| A4-AV2 | `_show_promotion_plan` has one caller, and only it passes `snapshot=` | Grep `_show_promotion_plan\|snapshot=(True\|False\|not)` in `*.py` | `__main__.py:3028` (the call), `:3634` (the definition); `ws_event_stream.py:656` (another function's keyword) | yes |
| A4-AV3 | No test asserts a refused dry run's tier table, plan or description | Grep `would refuse` in `tests/`; Grep `dry_run=True` in `tests/test_ad1341_*.py` | `would refuse`: records-snapshot `:699`, `:849` (the refusal's text, kept) and five unrelated files; `dry_run=True`: s1 `:476`, s3 `:246`, clean-slate `:281`, `:285` (no refusal) and `:376` (the overlap, exit 1 before the preflight), nature `:357`, `:463` (no refusal), records `:691`, `:698`, `:846` | yes |
| A4-AV4 | No test pins "the reason is recorded" | Grep `reason is recorded\|promotion skipped\|skipped with it` in `tests/` | records-snapshot `:363` ("skipped with it", unchanged) | yes |
| A4-AV5 | Only X12 asserts `(erased by the Captain);`, after its file is gone | Grep `erased by the Captain\|_snapshot_state` in `tests/test_ad1341_*.py` | records `:602` (after the rerun deleted the file); s3 review-cli `:84` (S3's pending listing) | yes |
| A4-AV6 | Only `prepare_snapshot` builds the temporary name | Grep `\.partial\|with_name\(` in `src/probos` | `records_snapshot.py:227`; `snapshot_manifest.py:254`, `provider_setup.py:871`, `:874` build other names | yes |
| A4-AV7 | In a dry run only `_show_promotion_plan` reaches `_nature_record`, and only `_nature_rows` sizes `procedures/` | Grep `_nature_record\(\|_get_file_size\(\|_open_read_only\b` in `__main__.py` | `_nature_record`: 3399 (the reset), 3456 (`pending`), 3659 (the dry run), 3868 (the veto); `_get_file_size`: 2730, 2750, 2851, 2911 (tier files), 2810 (`procedures/`) | yes; `pending` and the veto read through a link at `procedures` by design without `--clean-slate` (D12) |

## POSIX audit (A4, by reading; no Linux or macOS run)

| # | Where | Name or assumption | On Linux | A4 |
|---|---|---|---|---|
| 1 | `records_snapshot.py:155` | `stat.IO_REPARSE_TAG_MOUNT_POINT` | **breaks**: `AttributeError` (Windows-only name) | fixed (7.1) |
| 2 | `records_snapshot.py:154` | `getattr(status, "st_reparse_tag", 0)` | fine: the default | none |
| 3 | `records_snapshot.py:187` | `DirEntry.is_junction()` | fine: Python 3.12+ (`requires-python >=3.12`, CI 3.12), always False on POSIX; `is_symlink()` carries the check | none |
| 4 | `records_snapshot.py:114` | `os.link` onto an existing name; no hard links | fine: `link(2)` EEXIST is `FileExistsError` (refuses); EPERM or ENOTSUP is `OSError` (refuses); `fs.protected_hardlinks` limits only files the caller does not own | none |
| 5 | `records_snapshot.py:122` | `_remove_quietly` after the link | no sharing denial on POSIX (unlinking an open file succeeds); EACCES, EROFS or EIO there leaves the alias | fixed generally (`retained_alias`); A5: its identity proof needs a nonzero `st_ino` (A-R3-F1) |
| 6 | `records_snapshot.py:230`, `:235` | `open(temp, "xb")`, `os.fsync` | fine: `O_EXCL`, `fsync(2)`; the directory is not synced | R46 |
| 7 | `__main__.py:3307`, `3308`, `3323` | `os.path.normcase` | fine on Linux: the identity, and paths are case-sensitive, so exact; macOS case-insensitive volumes miss a case alias | R45 |
| 8 | `__main__.py:3307`, `3308`, `3323` | `Path.resolve()` of a missing path | fine: non-strict, resolves the existing prefix | none |
| 9 | `__main__.py:3479` | `st_mtime` as the generation's start | fine: nanoseconds on ext4; the name uses seconds (R27); tests set whole seconds with `os.utime` | none |
| 10 | `__main__.py:2696`, `:3659` | `_get_file_size`'s `rglob` and `_nature_record` through a refused symlink | **breaks** as on Windows (R2-B1) | fixed (the dry-run rule) |
| 11 | `__main__.py:4065`, `:4154-4158` | `shutil.rmtree(onerror=_force_remove_readonly)` | fine for read-only files; a read-only directory fails every time (fail closed); `onerror` warns on 3.12 (no `filterwarnings = error`) | R47 |
| 12 | `storage/sqlite_factory.py:36` | `resolve().as_uri()` and `?mode=ro` | fine: `file:///...`; a WAL store's `-shm` is created in a writable directory (R34) | none |
| 13 | both test files, `_link_dir` | `os.symlink(target, link, target_is_directory=True)` | fine: the flag is ignored; no privilege needed, so X7, X7c, X12d, X16, C7, C11 and C14 run, not skip; every link check reads `S_ISLNK` | none |
| 14 | X3 `unreadable`, X7b, X12, X17 | sharing violations, an `lstat` error | injected (`_copy_member`, `os.lstat`, `Path.unlink` doubles), platform-independent | none |
| 15 | `_snapshot_files`, `_tree` | `rglob("*")` | fine: dot files (`.partial`) are listed; 3.12 does not recurse through symlinked directories while expanding `**`, and no test relies on it | none |
| 16 | the three S6 test files | case, file modes, the user | no two paths differ only by case (Grep `.lower()`: environment variable names only); no `chmod` (Grep: none); CI runs as the runner user, not root | none |
| 17 | X18, X19, C15 | `records_snapshot.stat` swapped for a POSIX-shaped namespace | the native module's names less the 17 `FILE_ATTRIBUTE_*` constants `Lib/stat.py` defines on every platform: stricter, and no S6 module reads them (A5 corrects A4's "equal"); they run, never skip | none |

## Not verified (A4)

1. **Native POSIX.** No Linux or macOS run; the audit above is by reading. CI's ubuntu shards are the first POSIX execution of S6 (§15).
2. **Every test outcome** (analysis; the oracle measures): tests-first on `2a1b6319`'s code, 10 fail (X14b, X17, X18, X19 ×3, C13, C14 ×2, C15) and 92 pass across the three files.
3. **`os.lstat` on Windows** fills `st_dev` and `st_ino` (the file index), so `os.path.samestat` identifies two hard links: documented behaviour; reviewer A's `samefile()` confirmed it on the candidate, and X17's premise asserts it.
4. **Whether 3.12's `shutil.rmtree`** reads the Windows-only names: not read and not relied on (the tests swap `records_snapshot`'s `stat` only).
5. **Ruff line lengths** of the new lines: by count, all at or under 120; the orchestrator's lint confirms.

## A5 verification (2026-10-27, on `77b65917`, tree `d7d00d4f`)

Read with the Read and Grep tools on the candidate; the CPython sources fetched at tag v3.12.13.

```
src/probos/knowledge/records_snapshot.py
  68         class SnapshotRefused(Exception)
  146-154    lstat_or_none (only FileNotFoundError is None)
  173-175    temporary_name; 178-191 retained_alias: 188 both lstat_or_none, 189-190 either absent -> None, 191 samestat
  257        prepare_snapshot: temp = temporary_name(final)
src/probos/__main__.py
  3981-3984  _cmd_archive: asyncio.run(_erase_snapshot(...)); except Exception -> "The erasure failed", 1
  3987-4021  _erase_snapshot: 3989 import; 4000-4003 _snapshot_file_problem before the marker; 4009 the marker; 4014-4016 retained_alias, then the unlinks; 4017 except OSError
  4024-4043  _snapshot_file_problem: 4034 import; 4040 lstat_or_none(path); 4041 S_ISREG
src/probos/cognitive/builder.py  3116 ("file", st_dev, st_ino) if info.st_ino else ("path", key): the repository's own rule
tests/test_ad1341_s6_records_snapshot.py
  91-94      _snapshot_files (sorted; a .partial included); 179-180 _erasures (erased_at, erase_reason)
  902-910    _posix_stat; 955-971 X17b; 974-990 X18, whose scan (986-990) names knowledge/nature_description.py
tests/test_ad1341_s6_clean_slate.py  465-472 _posix_stat
CPython v3.12.13 Doc/library/os.rst  st_ino: "Platform dependent, but if non-zero, uniquely identifies the file for a given value of st_dev"
CPython v3.12.13 Lib/stat.py  17 FILE_ATTRIBUTE_* constants at module level, unconditionally; then try: from _stat import *
logs/ad1341s6r3/review-ad1341s6-a-r3.md  A-R3-F1, its probe and its outputs on 77b65917 and 2a1b6319
```

## Absence Verified (A5, 2026-10-27)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A5-AV1 | Only the erasure calls `retained_alias` and `_snapshot_file_problem`; no other S6 code compares `st_ino` | Grep `_snapshot_file_problem\|retained_alias\|samestat\|st_ino\|class SnapshotRefused` in `src`; Grep `retained_alias\|_snapshot_file_problem\|lstat_or_none\|temporary_name` in `tests` | `src`: `records_snapshot.py:116` (a docstring), `:178`, `:183`, `:191`; `__main__.py:3989`, `:4014` (`retained_alias`), `:4000`, `:4024` (`_snapshot_file_problem`); every other `samestat`/`st_ino` hit is outside S6 (`builder_paths.py`, `builder.py`, `codebase_index.py`, `workspace.py`, `authority.py`, `file_access.py`); `tests`: none of the four names (X17's and X17b's names contain `temporary_name`; `test_ad482_*` calls another class's `_temporary_name`) | yes; A5 adds the second call, in `_snapshot_file_problem` |
| A5-AV2 | No test injects an `lstat` error into the erasure (A5 moves an alias `OSError` from after the marker to before it) | Grep `lstat` in `tests/test_ad1341_s6_*.py` | records-snapshot `:739-746` (X7b, the root's inspection by `plan_snapshot`), `:935`, `:967` (X17's and X17b's premises, real calls) | yes |
| A5-AV3 | Only X17 and X17b put a file at the temporary name | Grep `\.partial` in `tests/test_ad1341_*.py` | records-snapshot `:92` (a docstring), `:926`, `:934` (X17), `:965` (X17b) | yes; both have real, nonzero indices, so neither path changes |
| A5-AV4 | No S6 module reads a `FILE_ATTRIBUTE_*` name or `st_file_attributes` | Grep `FILE_ATTRIBUTE_\|st_file_attributes` in `src/probos` | `security/file_access.py:507`, `repository_instructions.py:190`, `cognitive/swe_harness/tools.py:79`, `:174`, `:192`, `:214`: none in S6 | yes |

## Not verified (A5)

1. **Every test outcome** (analysis; the oracle measures): on `77b65917`'s code, X17c fails at the first erasure's `== 1` (exit 0, the other file removed) and the other 102 cases of the three files pass; on A5's code all 103 pass.
2. **A real file system that reports `st_ino` 0** where a hard link succeeds: none named and none run (R48).
3. **That `st_dev` needs no guard:** CPython documents the nonzero qualifier on `st_ino` only, and the two names are in one directory, so they share a device. Not run.
4. **The erasure's cost:** the preflight's `retained_alias` adds two `lstat` calls, so an erasure with no alias goes from 5 to 7 in the snapshot module (reviewer A measured 5 on `77b65917`). Not measured.

## Absence Verified (2026-10-27)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| S6-AV1 | Only `archive_promotion.py` calls `promote_entry` in `src` | Grep `promote_entry\(` in `src` | `archive_promotion.py:435`, `:578`, `:584`; the definition `archive_store.py:501` | yes; 7.8 adds a fourth call in the same module |
| S6-AV2 | `procedures/` is in no reset tier, and nothing reads the procedures' YAML copies back | Grep `"procedures"\|procedures/` in `__main__.py`; Grep `safe_load\|read_text\|\.yaml` in `cognitive/procedure_store.py` | `__main__.py`: none; `procedure_store.py`: the two writes `:713`, `:1731`, no read | yes |
| S6-AV3 | No `src` code switches on `SourceKind` members outside `archive_promotion.py`; no other module spells the kind strings | Grep `SourceKind\.[A-Z_]+` (count) and `"(exit_note\|after_action\|captains_log\|notebook_finding)"` in `src` | 10, all in `archive_promotion.py`; the strings only as `lessons.py` key constants (`:55`, `:268`), the enum itself, `records_store.py:1278` (a retention map) and an ontology comment | yes |
| S6-AV4 | No snapshot reader, and no S6 name exists yet (`archive_snapshots`, `nature_clearances`, `ship-records-snapshots`, `NATURE_DESCRIPTION`, `clean_slate`) | Grep those names in `src` | none | yes; §7 introduces each, and X13/C8 pin their users |
| S6-AV5 | `_show_promotion_plan`, `_show_confirmation_prompt` and `_show_dry_run` each have one caller, `_cmd_reset`, and no test calls them | Grep the three names in `src` and `tests` | `src`: the definitions and `__main__.py:2976`, `:2978`, `:2983`; `tests`: none | yes |
| S6-AV6 | No test pins the reset summary's lines or names `clean_slate` | Grep `Preserved:\|Nature kept\|clean_slate` in `tests` | four class names containing "Preserved" (unrelated) | yes |
| S6-AV7 | No census test restricts the importers of `archive_promotion` (so `nature_description.py` may import its prefix) | Grep `importers\|rglob\("\*\.py"\)` in `tests/test_ad1341_*.py` | the censuses listed in §11, none on `archive_promotion` importers | yes |
| S6-AV8 | `ArchiveStore` is not in the architecture baseline (it sits at 15 methods, not above) | Grep `archive_store` in `architecture-baseline.yaml` | none | yes; S6 adds no method |

## Not verified (the orchestrator verifies by running)

1. **Every test outcome.** No pytest was run by either Architect run. §6's "first assertion to fail on the base" is analysis. The focused gates of §4 and the census of §10 are measured on the oracle.
2. **The live archive (read-only; `%LOCALAPPDATA%\ProbOS\archive\archive.db`, the vessel stopped since 2026-10-25 22:31:43 local).** Taken as given from #1569: schema v1, 0 rows on 2026-10-26. Verify by opening it immutable (`file:...?mode=ro&immutable=1`): `user_version` 1, and that neither `archive_snapshots` nor `nature_clearances` exists yet. Then, on a **copy** in a temp directory, never the original: `ArchiveStore.initialize` adds both tables and keeps `user_version` 1 (no S6 test opens a pre-S6 file with rows; register R25).
3. **The live data directory (read-only; `%LOCALAPPDATA%\ProbOS\data`).** For the Captain, not for the build: the size and file count of `ship-records/` excluding `.git/` and `procedures/` (against 100,000 files and 2 GiB), whether any link or junction is inside it (a `--full` reset would refuse), whether `ontology/instance_id` exists and its modification time (the generation's start), and the number of `procedure_records` rows with `created_at` at or after it (what the description would list). Read-only; nothing under the data directory is opened for writing.
4. **Junctions on the build host.** X7 and C7 make a junction on Windows (`_link_dir`) and a symlink elsewhere, and skip where the host refuses. Measure that neither is skipped on the Captain's Windows host.
5. **Python 3.12's `DirEntry.is_junction()` and `Path.is_junction()`** return False on POSIX, so the `is_symlink()` half carries the check there.
6. **`zipfile` with `force_zip64=True` and `allowZip64=True`** produces a ZIP that Windows Explorer and `bagit-python`'s validator open; not run. X8 reads it back with `zipfile` only.
7. **The full suite** is the orchestrator's single broad gate after M4.

## S5 anchors this contract depends on

| S6 location | S5 text it depends on | On `7cb0b212` |
|---|---|---|
| 7.7 SEARCH | `AFTER_ACTION_REPORT = "after_action"  # AD-1341 S5: a lesson after a flagged event, endorsed by the chain; cites episodes` | `archive_store.py:104` |
| 7.11 SEARCH | S5's two comment lines and the closed-set assertion with `"after_action"` | `tests/test_ad1341_s1_archive_store.py:225-229` |
| 7.8 SEARCH | **none from S5**: `vetoed=tuple(vetoed),` … `class PendingSource:` is S3's text; S5 (A3 to A5 included) adds `_captains_log_day_end`, `is_settled` and `promote_settled` after it (`:458-625`) and did not touch it | `archive_promotion.py:452-457` |
| M2's focused gate | `tests/test_ad1341_s5_after_action_format.py`, `tests/test_ad1341_s5_continuous_promotion.py` exist | present |
| §8 anchors | none from S5: `# ProbOS Progress` and `### Explicit delegation models ...`; S5's entries sit above them | `PROGRESS.md:1`, `DECISIONS.md:856` |
| D1 | S5's continuous promotion plans over Ship's Records only, so it never archives a description or takes a snapshot | `archive_promotion.py:561` (`promote_settled`) |

Every other SEARCH anchors on S1 to S4 text or older, or on S6's own earlier milestone. If S5's round 2 renames `AFTER_ACTION_REPORT`, changes its comment, or edits the S1 closed-set test's comment lines, 7.7 and 7.11 change with it (the REPLACE re-emits S5's line verbatim): return them to the Architect.

## 12. Deterministic gate checks, resolved up front

- **No config field**, so nothing moves in the AD-1152 default-config hash, the AD-1270 E1 facade baseline and its pinned counts, E2i's true-leaf pin, the AD-1185 profile census or `config-reference.md`. The gate's config preflight is unaffected.
- **Store registry, rule 11 (`baseline-table-drift`):** `ArchiveStore._SCHEMA` gains `archive_snapshots` (M1) and `nature_clearances` (M3); 7.4 and 7.14 add each to the archive store's row in `store-baseline.yaml` in the same milestone. `archive_ledger.py` holds no `CREATE TABLE`, so it is no store of its own. `check_store_registry.py --check` is in M1's and M3's focused gates.
- **AD-1270 architecture principles:** `ArchiveStore` gains no method (15, the trigger is `> 15`). `ArchiveLedger` has 7 methods (8 after M3). No new class body passes 500 lines. No new `sqlite3.connect` or `aiosqlite.connect` (the ledger and the description use the `ConnectionFactory`); the one baseline row for `_cmd_reset` (`sqlite3.connect`, count 2) is unchanged. `check_architecture_principles.py --check` is in every code milestone's gate.
- **Layer boundaries:** the three new modules sit in `knowledge/` and import `knowledge.archive_store`, `knowledge.archive_promotion`, `knowledge.lessons` and `protocols` only; `__main__.py` imports them lazily, as it does S1's.
- **Censuses:** S1's `promote_entry` (only `archive_promotion.py`), S3's `source_state` (only `archive_promotion.py`, kept by `review_nature_description`), `veto_source`, `erase_entry` and `record_generation` (only `__main__.py`): §7 adds no other naming file.
- **S1's import census of `archive_promotion.py`** (`test_ad1341_s1_promotion.py:413-423`): unchanged; 7.8 adds no import.
- **S1's closed `SourceKind` set:** updated in 7.11 with an inline reason, never loosened.
- **AD-1343's seam registry:** S6 starts no agent's work and makes no model call; nothing to register.
- **The AD ledger** (`gen_ad_ledger.py --check`) and `open-ads-report.md` are M4's.
- **A2:** no store table, `ArchiveStore` or `ArchiveLedger` method, config field or event type is added. `records_snapshot` gains three public functions (`lstat_or_none`, `is_link_status`, `is_link_or_junction`), imported only by `__main__.py` (X13 holds). `archive_promotion` gains a private `_nature_state` that names `source_state` (S3's census holds: the same module). `record_generation` stays named in `src` by `__main__.py` alone. `_cmd_reset` grows about 20 lines; no class body changes. `knowledge/` imports only `stat` (the standard library), so the layer rule holds.
- **A4:** no table, method, config field or event type. `records_snapshot` gains two public functions (`temporary_name`, `retained_alias`) and a private constant; only `__main__.py` imports the module (X13 holds). `_show_promotion_plan` loses a keyword (one caller, A4-AV2). `_cmd_reset` grows four lines; `_erase_snapshot` and `_snapshot_state` two each. No new import outside the standard library.
- **A5:** no table, method, config field or event type. `retained_alias` gains one guard and one refusal; `_snapshot_file_problem` becomes its second caller (A5-AV1); `_erase_snapshot` catches `SnapshotRefused` beside `OSError`. The only new imports are names from `records_snapshot` itself.

## 13. Prior Art and Blind Spots

Date used for `docs/research/reference-projects.md`: 2026-10-27. The snapshot is generic preservation plumbing with one outside analogue examined; the description and clean slate are ProbOS-specific.

- **BagIt (RFC 8493), absorbed.** The snapshot is a serialized bag: one top-level directory named after the file, `bagit.txt`, `bag-info.txt` (with `Payload-Oxum` and `External-Identifier`), `manifest-sha256.txt` and `data/`. The manifest path encoding follows 2.1.3 exactly (LF, CR, CRLF and `%`, and only those). Any BagIt validator checks an extracted snapshot. A tag manifest is optional and left out. https://www.rfc-editor.org/rfc/rfc8493.html
- **Library of Congress `bagit-python`, considered, not a dependency.** Its known gap (bagit-python issue 157: `%` not encoded) is why the encoding is hand-written and pinned by X8 (P-10). Adding a dependency for 80 lines was rejected. https://github.com/LibraryOfCongress/bagit-python/issues/157
- **Write, fsync, verify, publish without replacing**, adapted (A2, A-F4). `os.replace` replaces a name that appears after any check, so publication is a hard link: `link(2)` fails with `EEXIST`, and Windows' `CreateHardLinkW` fails when the name exists. The temporary name is then removed, and the row is still recorded first (D6).
  - The repository's own precedent is `security/file_access.py:767-783` ("Atomic, no-replacement publication", by `os.link`).
  - AD-1265's backups use `os.link` with a logged copy fallback (`infrastructure/backup.py:739-746`); A2 does not copy the fallback, because a fallback that may replace is the defect.
  - Rejected: Windows-only `os.rename` (it replaces on POSIX) and Linux-only `renameat2(RENAME_NOREPLACE)`.
  - No web search: the primitive's semantics are the platforms' documented behaviour, and the repository already relies on them.
- **Voyager (skill library), considered, deferred** (reference row: passing, 2026-10-15; not overdue). A skill library keeps a description beside each skill; ProbOS's description entry is culture's record of nature, not the retrieval index, so nothing more is taken. AG-UI (never reviewed) is unrelated to this slice and not examined.
- **Internal prior work:** AD-524's item 1 (`roadmap-era-5-completed.md:2523`), the 2026-10-16 amendment (nature, culture, nurture; the Captain's memory note "Nature, Culture, Nurture"), S1 C1 (who may read the archive), S4 A5 (`os.walk` swallows errors: hence the explicit `os.scandir` walk), BF-906 (`mode=ro`).

**Blind spots named (each decided):**
1. A link inside Ship's Records could carry the snapshot out of the data directory: refused, never followed (D5, X7).
2. A file that changes while it is copied: refused by size (X3 `grew`, `shrank`).
3. An existing v1 archive must gain the two tables: `_SCHEMA` runs at every open (`archive_store.py:479`); measured on a copy (Not verified 2).
4. A snapshot is the one place a private note survives a `--full` reset; a later reader must apply the classification rule (R5).
5. The RA3-1 note also names `_archived/*.md`, which the listing skips by design, not because it cannot decode them (R18).
6. Two resets within one second would name the same file; the second refuses (fail closed; R27).
7. `--clean-slate` with `--skip-promotion` records the clearance with no description (R19).
8. A2: a same-user process that swaps a path between the preflight and the write; the write-time checks narrow the gap, and the pidfile excludes only the vessel (R28).
9. A2: `security/file_access.is_reparse_point` (any reparse point) was considered for the link checks and not imported: `knowledge/` may import only `substrate` (`tests/test_layer_boundaries.py:49`), and treating every reparse point as a link would also refuse cloud-file placeholders, a change beyond the findings. D5's rule (a symbolic link or a junction) lives in one place, `records_snapshot.is_link_status`.
10. A2: a file system without hard links under the archive refuses every `--full` reset that has records to keep (R36).
11. A4 (A-R2-F1), absorbed: a platform-conditional standard-library name. CPython adds `IO_REPARSE_TAG_SYMLINK`, `_MOUNT_POINT` and `_APPEXECLINK` to `stat` inside `#ifdef MS_WINDOWS`, and `Lib/stat.py` has no fallback, so the value is the module's own, `0xA0000003`, as Go's `internal/syscall/windows` defines it itself. https://github.com/python/cpython/blob/v3.12.13/Modules/_stat.c ; https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4 ; https://golang.google.cn/src/internal/syscall/windows/reparse_windows.go
12. A4: the tests stand in for POSIX at the module boundary (`records_snapshot.stat`), not by deleting the name from the interpreter's `stat`: `ntpath.isjunction` (v3.12.13) compares with `stat.IO_REPARSE_TAG_MOUNT_POINT` outside its `try`, so a global deletion would make the test depend on the standard library's internals. https://github.com/python/cpython/blob/v3.12.13/Lib/ntpath.py
13. A4 (A-R2-F2): link-then-unlink publication leaves a second name when the unlink fails. It is the same file, so identity (`os.path.samestat` of two `lstat` results), not the name or the content, decides what the erasure removes; a copy with equal bytes is left (X17b).
14. A4, the POSIX audit (§11): macOS's case-insensitive volumes defeat `normcase` (R45); the snapshots directory is not synced after the link (R46); a read-only directory inside `procedures/` fails the clean slate every time on POSIX (R47); a temporary file with no final name is not the erasure's to remove (R44). No row of `docs/research/reference-projects.md` covers platform constants; none was examined (date used 2026-10-27).
15. A5 (A-R3-F1), absorbed: a documented qualifier is part of an identity predicate. CPython documents `st_ino` as identifying a file only if nonzero, and `os.path.samestat` compares `st_dev` and `st_ino` without that check, so the erasure checks it first and refuses when it fails. This repository already applies the rule: `cognitive/builder.py:3116` keys a file by `(st_dev, st_ino)` only when `st_ino` is nonzero, and by path otherwise. No external search: a one-line platform contract whose source was fetched. https://github.com/python/cpython/blob/v3.12.13/Doc/library/os.rst

## 14. Diff Reviewer: properties to verify

Each holds on the assembled tree. Brief the cross-family reviewer with these, one milestone at a time.

**M1:**
1. A tier 3 reset that completes has, before its tier loop ran, one published snapshot whose payload equals every regular file of `{data_dir}/ship-records` except the top-level `.git/` and `procedures/`, byte for byte, and one `archive_snapshots` row naming it with the file's SHA-256.
2. A tier 3 reset whose snapshot the preflight refuses exits 1 having opened no archive: no promotion, description, row, generation or file. The preflight refuses a link, junction or special file at the root or inside, a root that cannot be inspected, either bound, no instance id or one that cannot name a directory, and a link or junction at the snapshots directory or the timeline's. A snapshot that fails while it is written or checked exits 1 with every data file unchanged, no snapshot or temporary file, no `archive_snapshots` row and no `generations` row. A publish that fails, or a crash between the row and the publish, leaves its row, never deleted, which `probos archive snapshots` shows as `(missing)`, and no `generations` row (A2, A-F7).
3. No snapshot is ever written over, at prepare or at publish, even by a name that appears after every check: publication is a hard link, and a file system without hard links refuses. The row is recorded before the file is published.
4. `plan_snapshot` never follows a link or junction, the root included; only a root that is not there is an empty plan; every other `OSError` of the root's `lstat` and of the walk propagates. The read-back reads every member to its end, the tag files included, and refuses a bag whose members are not exactly those written, in order (A3: an extra member too). `is_link_status` names no `stat` attribute a POSIX build lacks: a POSIX status (no `st_reparse_tag`) is judged by its mode, a Windows one by its mode or a junction's tag (`0xA0000003`), and no other reparse tag is a link (A4, A-R2-F1).
5. The erasure of a snapshot deletes only a regular file, at a path that matches the snapshot name pattern, inside a snapshots directory and a timeline directory that are neither links nor junctions; otherwise it exits 1 with nothing marked or deleted. It marks its row before it deletes the file, keeps the first reason (the ledger's `AND erased_at IS NULL`, even when two erasures both read the row unmarked), and never deletes a row. A temporary name the publish could not remove after its link (the same file, by `lstat` device and file id) is removed first, then the snapshot's name; another file at that name is never touched; while either remains the erasure exits 1, the listing says the file remains, and the same command finishes it (A4, A-R2-F2). A file index of 0 proves nothing: when both names exist and either reports `st_ino` 0, the erasure refuses before its marker (exit 1, both names and the row unchanged); a zero index with no temporary name beside the snapshot erases as before (A5, A-R3-F1).
6. Only `__main__.py` imports `records_snapshot` or `archive_ledger`; no agent, service or Oracle tier reads a snapshot.
7. A tier 2 reset and a dry run write no snapshot; a dry run opens no archive. A dry run whose reset would refuse says so and never says a snapshot would be kept (A-F5). It prints the refusal and nothing else: no tier table, no promotion plan, no description, and nothing is read or sized through the refused path (A4, R2-B1, C-R2-F1).
8. `--skip-promotion REASON` at tier 3 writes no snapshot and says so.
9. At every tier, a reset refuses (exit 1, nothing opened) when the Ship's Archive's file or its snapshots directory, resolved through links and junctions and compared with the platform's case rule, is equal to, inside or around anything the reset deletes.

**M2:**
10. Every tier 2 and 3 reset with an instance id and at least one procedure created since `ontology/instance_id`'s modification time archives exactly one `nature_description` entry for the timeline, classified `ship`, citing no episode. A retried reset of the same generation archives none: the first is kept, whatever changed, and `pending` shows it as already archived (A2, B-F2). It is archived after the snapshot, so a snapshot that fails leaves none.
11. The description's content never contains a procedure's `content_snapshot` or any column but the nine §7.9 reads, lists at most ten procedures in order of completions, most first (ties by creation, then id), is at most 900 characters, and its whole entry passes the Oracle tool's 1,200-character cut intact.
12. `procedures.db` is opened only read-only (`mode=ro`) and its database bytes are identical after the reset reads it; for a WAL-mode store SQLite may create or touch the `-wal` and `-shm` files beside it (B-F4); a missing store is never created.
13. `pending`, `veto`, `--dry-run` and the reset build the description with one function (`_nature_record`). `pending` and the veto's confirmation print its title and whole text (B-F1). A veto by kind and reference keeps it out whatever its content at the reset.
14. Only `archive_promotion.py` names `promote_entry` and `source_state`.

**M3:**
15. `--clean-slate` deletes `{data_dir}/procedures/` and nothing else beyond the tier's own files; `config/skills`, `cognitive_skills.db`, `skill_grants.db`, `profile_qualifications.db`, the archive, the snapshots and `archives/` are byte-identical.
16. The `nature_clearances` marker is committed before any deletion; a marker that cannot be written deletes nothing.
17. A deletion that fails leaves every crew file in place (the tier loop does not run), records no generation close, and exits 1; the same command finishes it with a second marker and one close. This holds with `--skip-promotion` too (C-F3). The skip's message, printed before the clearance and the close, never says the reason is recorded; it says it will be, with the close (A4, C-R2-F2).
18. `--clean-slate` with `--soft`, or with the archive disabled, exits 2 having changed nothing.
19. A link, junction or file at `{data_dir}/procedures`, or a name there that cannot be inspected, is refused (exit 1) before anything is read through it, archived, recorded or closed, so every archive table is unchanged. It is checked again where it deletes (B-F3, C-F2). A dry run with `--clean-slate` and such a shape prints the refusal and nothing else: `procedures.db` is not opened through the link, its target gains no `-wal` or `-shm`, and the directory is not sized (A4).
20. With `--clean-slate`, an archive or snapshots directory inside `{data_dir}/procedures/` refuses the reset at tiers 2 and 3 and in the dry run; without the flag it does not (C-F1).
21. Without `--clean-slate`, `procedures/` is unchanged at every tier, and the generation is closed after the promotion as before.

## 15. Acceptance criteria

- [ ] M1 to M4 built in order, one Builder delegation and one local commit each, staged by explicit path.
- [ ] Each new test file failed at import on its milestone's base (§6) before the code was written.
- [ ] Each milestone's focused gate (§4) passes with `-n 0`, with `check_store_registry.py --check` and `check_architecture_principles.py --check` where listed.
- [ ] No test or build step touches `%LOCALAPPDATA%\ProbOS`, `d:\ProbOS\data` or any real data directory; no `probos reset` or `--clean-slate` runs outside the tests' `tmp_path`.
- [ ] Each of M1, M2 and M3 has a cross-family review (`gpt-6.1-sol`) against §14, with its findings repaired.
- [ ] Amendment A2: round 2 of the cross-family review, one reviewer per milestone, against §14 as amended (1 to 21); the §10 campaign rerun on the assembled tree (70 rows: P-1 to P-36, D-1 to D-16, K-1 to K-18), with every row killed or returned to the Architect.
- [ ] Amendment A4: round 3 of the cross-family review, A4's delta only, one reviewer per milestone, against §14 as amended; a round 4 needs the Architect's decision first. The A4 rows of §10 (P-34 as rewritten, P-37 to P-43, K-19) run on the assembled tree, every row killed or returned to the Architect. CI's ubuntu shards pass the three S6 files on the pushed head (their first POSIX execution).
- [ ] Amendment A5: round 4 of the cross-family review, reviewer A alone, on A5's delta (`records_snapshot.py`, `__main__.py`, the two S6 test files A5 touches), against §14 (5) as amended. P-44 and P-45 run on the assembled tree, each killed by X17c or returned to the Architect. M1's focused list passes on M1's stage alone (X18). Any new finding returns to the Architect; there is no round 5 without a decision.
- [ ] The §10 campaign runs once on the assembled tree after an unmutated baseline that passes; every row is killed by a named test, or the row returns to the Architect.
- [ ] `tests/test_ad1341_s1_archive_store.py` and `tests/test_ad1341_s3_veto_store.py` pass unloosened (7.11's inline reason; S3's census holds).
- [ ] `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass after M4.
- [ ] The orchestrator's single broad gate passes with its receipt: `scripts/run_test_gate.py --label ad1341-s6 --receipt logs/gates/ad1341-s6.receipt.json`.
- [ ] Not verified items 2 and 3 are run read-only and reported to the Captain before the first live `--full` reset.
- [ ] The register rows below are posted on #1523.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

What S6 finds and does not fix, each with its reason. S1 RA3-1 closes (D9). F-649 closes for tier 3 (D9), and F-660 (f)'s lossy listing no longer loses a file at tier 3. S5's own rows stay as S5 recorded them.

**R1.** Automatic after-action triggers (S5 R1, "Owner: S6 or a follow-up"): left to a follow-up; not one of S6's three items, and each trigger spends unattended model turns.
**R2.** A `--full` reset still deletes `scout_reports/` and `workforce.db` with no snapshot; the issue scopes the snapshot to Ship's Records.
**R3.** A custom `records.repo_path` outside the data directory is not deleted by `--full`, so it is not snapshotted; nothing is lost, but nothing is kept either.
**R4.** The snapshot leaves out `.git/` (the history); the working tree is what the promotion read. A Captain who wants the history copies the repository before the reset.
**R5.** A snapshot keeps every classification, private included. Any future reader (AD-524 items 2 and 3) must apply the classification rule before any agent sees a snapshot's content.
**R6.** Erasing a snapshot unlinks the file without overwriting its bytes; recovery from the disk is possible until the space is reused.
**R7.** AD-1265's backups copy `*.db` files only, so snapshot ZIP files are not backed up; `archive.db`, with the rows, is.
**R8.** The bounds (100,000 files, 2 GiB) are module constants, not config: no measured need yet, and a config field moves five pins.
**R9.** The generation's start is the modification time of `ontology/instance_id`; a restored, copied or touched data directory shifts it, and with it which procedures the description counts.
**R10.** Skills are not described: the catalog's `origin` is rewritten as `internal` at every boot (`skill_catalog.py:283-296`). A durable origin is the prerequisite for describing forged skills.
**R11.** The procedures' YAML copies in `ship-records/procedures/` survive a tier 2 `--clean-slate` and are deleted unsnapshotted at tier 3; nothing reads them back (S6-AV2).
**R12.** `--clean-slate` leaves `profile_qualifications.db` (AD-1287, not wired, insert-only) alone; revisit when AD-1287 is wired.
**R13.** Writers outside ProbOS (F-643, F-657): the snapshot copies whatever such a writer left, as Ship's Records held it.
**R14.** A failure after the snapshot is published (archiving the description, the clean slate, or closing the generation) leaves a complete snapshot; the rerun takes a second one. Both are listed; the Captain may erase one.
**R15.** A publish that fails (X3b), or a crash between recording the row and the link, leaves a row, never deleted, whose file is missing; `probos archive snapshots` shows `(missing)`.
**R16.** A snapshot copies and reads back up to 2 GiB synchronously, with no progress output.
**R17.** A Markdown file Ship's Records cannot decode is kept in the snapshot and named, but still never promoted.
**R18.** The RA3-1 note also names `_archived/*.md`, which the listing skips by design (`records_store.py:1033`), not because it cannot decode them.
**R19.** `--clean-slate` with `--skip-promotion` records the clearance marker with no nature description: the skip covers every promotion.
**R20.** The `started is None` branch in `_snapshot_ship_records` (the instance id removed by another process during the reset) has no test; the pidfile makes it unreachable from ProbOS itself.
**R21.** `probos archive snapshots`' `(not a snapshot's name: never opened)` state is display only and has no mutation row; the erasure's own check has one (P-12).
**R22.** `_record_nature_clearance`'s log-and-degrade count (`-1` for a store that cannot be counted) is pinned by the record's constructor only (C10), not end to end.
**R23.** The `is_file` refusal (a special file, a FIFO) is reachable on POSIX only and is not tested on the Captain's Windows host.
**R24.** The in-loop `copied > item.size` guard has an outcome-equivalent mutant (the size check after the loop refuses too); it bounds how much of a growing file is read.
**R25.** No S6 test opens a pre-S6 v1 archive that already holds rows; the tables come from `_SCHEMA`'s `CREATE TABLE IF NOT EXISTS` at every open. Measured once on a copy of the live archive (Not verified 2).
**R26.** `probos archive erase-snapshot`'s `(missing)` path after an interrupted publish (R15) erases a row whose file is absent: `unlink(missing_ok=True)` succeeds and the row is marked. Correct, but untested.
**R27.** Snapshot names have one-second resolution; two `--full` resets of one timeline within a second would collide, and the second refuses (fail closed).
**R28.** (A2) The preflight's checks are repeated where each write happens (the snapshot's walk and destination, the clean slate's `_nature_dir_problem`, the erasure's `_snapshot_file_problem`). A same-user process that changes a path between a check and its write is outside ProbOS; the pidfile excludes only the vessel. A change caught at write time refuses after the earlier archive writes, which are idempotent. Reach: injected only.
**R29.** (A2, A-F8, P3, injected only) `ArchiveLedger.initialize` checks `user_version` only, so an archive from before S6, opened by the ledger alone, passes, and its first read raises `OperationalError` (fail closed). Every production open follows `ArchiveStore.initialize` on the same file (`_open_ledger`; `_snapshot_ship_records` runs inside `_promote_into_archive` after `archive.initialize()`). A future caller that opens the ledger alone must open the store first.
**R30.** (A2, B-F2) One description per generation: a generation that resumes after a refused reset and develops more procedures keeps its first description, and the retry reports `present`. Erasing that entry keeps the source out for good (S3), so the generation cannot be re-described. Reach: ordinary but narrow (a refusal after the description, a boot, a retry); with A2's order only a failed clean slate or close leaves it.
**R31.** (A2) `probos archive snapshots` reports `(present)` by `is_file()`, which follows a link: display only. The erasure validates with `lstat` (P-30 to P-32).
**R32.** (A2) A tier 3 reset checks only the current timeline's directory under the snapshots directory for a link; an older timeline's directory that is a junction is not inspected by the reset (the erasure refuses to delete through it). Reach: injected only.
**R33.** (A2) Every reparse point other than a symbolic link or a junction (a cloud placeholder, an app-exec link) is not treated as a link by D5's rule; `security/file_access.is_reparse_point` is stricter and is not imported into `knowledge/`.
**R34.** (A2, B-F4) A read-only open of a WAL-mode `procedures.db` may create or touch its `-wal` and `-shm` files; the main database is byte-identical (N11). `immutable=1` would avoid them, but is unsafe while the vessel writes (the dry run and `pending` run beside a live vessel).
**R35.** (A2) A tier 3 reset walks Ship's Records twice (the preflight's plan and the snapshot's), names and sizes only, up to 100,000 entries.
**R36.** (A2, A-F4) A file system without hard links under the Ship's Archive (FAT32, exFAT, some network shares) refuses every `--full` reset whose Ship's Records hold a file (fail closed). `--skip-promotion` or moving `archive.db_path` are the ways through.
**R37.** (A2, C-F3) A tier 2 or 3 reset opens the archive once more, to record the generation's close (one connection, one INSERT).
**R38.** (Process, S6 round 1) Every refusal test on a destructive path captures *all* durable state before and after (every archive table, the data directory, the link's target) and asserts it unchanged; "exit 1 and the target intact" is not a refusal test. All three reviewers found the same class in three milestones: a guard placed after the first write (the link refusal after the description was archived; the generation closed before a clearance that could fail), or one path of a set checked (the archive against the tier targets but not the clean slate's; the archive file but not the snapshot destination; names but not the components they resolve through). Every test asserted the exit code and the target, so all passed.
**R39.** (Process) A contract that adds a deletion target or a protected path lists the deletion set × protected paths cross product in §5 and §14, with one test per new pair and a link at every component of each path (root, intermediate, final), not only inside a walk; and puts every knowable refusal in one preflight that the dry run shares.
**R40.** (Process) Every refusal branch of a new destructive function gets a §10 row or a register line saying why not. The file branch of `_clear_nature` had neither; the Builder flagged it, and a mutant disabling it left all 21 tests passing.
**R41.** (Process, A3) A guard added behind an older one can take the older guard's only killing data. A2's tag read-back also refuses a missing tag member, so X3's `member-missing` no longer reached P-8's member-list check. That check then refused only a member the bag does not list, and no test wrote one; the census found it, not a review. When an amendment adds a guard on a path that already has a §10 row, recheck that row's fault data against the new guard, and give each guard a fault only it refuses.
**R42.** (Process, A4) A claim about a platform, recalled and never run, became a P1. A2 took `stat.IO_REPARSE_TAG_MOUNT_POINT` to exist on POSIX ("as I recall"). Every test, review and census ran on Windows, where the name exists, so no passing case could see it; the first POSIX run would have been CI after the push. A contract that uses a platform-conditional name (from `stat`, `os`, `signal`, `fcntl`, `_winapi`, `msvcrt`) cites its source in its verification, prefers a literal of the documented value, and adds a test that stands in for the other platform at the module under test's boundary (a POSIX-shaped namespace for that module's import, never a deletion from the interpreter's module). A contract that touches the file system carries a POSIX audit (§11).
**R43.** (Process, A4) A refusal has to govern every consumer of what it refuses. A2's preflight refused a link at `procedures` before the reset read through it, and its tests drove the executing reset only; the dry run, a second consumer of the same refusal, still sized the path and opened the store through it. When a check refuses a shape, list every path that reads that shape (the reset, its dry run, its confirmation, the listings) and give each a test with the refused shape populated (a real target with content and sidecar-prone state, counting opens), not only an exit code.
**R44.** (A4, A-R2-F2's residue; P3, injected only, not a regression) A publish whose link fails and whose temporary file then cannot be removed leaves a complete snapshot at `.{name}.partial`, with its row shown `(missing)` (R15). With no final name the erasure cannot prove by file identity that the file is that snapshot, so it leaves it. A digest check against the row's SHA-256 could; not built. Reach: two faults at once; `f9afeb59`'s `os.replace` had the same.
**R45.** (A4, POSIX audit) On macOS, `os.path.normcase` is the identity while APFS and HFS+ volumes are case-insensitive by default, so S1 A4's overlap (S1's archive comparison and A2's snapshots) does not see an `archive.db_path` spelled in another case as inside the data directory. Linux, where CI runs, is case-sensitive, so the comparison is exact there. Reach: an operator's configuration on macOS; no macOS host is tested.
**R46.** (A4, POSIX audit) Publication does not `fsync` the snapshots directory, so after a power loss the final name may be missing while its row exists: `(missing)`, R15's state.
**R47.** (A4, POSIX audit) `_force_remove_readonly` (shared with the tier loop since before S6) makes the failing entry writable, not its parent, so on POSIX a read-only directory inside `procedures/` fails the clean slate's deletion every time: the marker is recorded and the reset refuses before its tier loop until the mode is fixed (fail closed). No S6 test creates read-only content.
**R48.** (A5, A-R3-F1's reach; P2, injected only) No file system is known on which `os.link` succeeds and `lstat` reports `st_ino` 0. Reviewer A projected 0 at the module's status boundary; no real such file system was run. On one, an erasure with a `.{name}.partial` beside the snapshot refuses (exit 1, both names kept) until the Captain removes the temporary name by hand: fail closed, never a guess. A digest check against the row's SHA-256 would prove equal bytes, not one file (X17b keeps such a copy), so it is not the way out.
**R49.** (Process, A5) Two lessons of round 3. (a) A standard-library predicate used as a proof carries its documented preconditions: `samestat` is only as good as `st_ino`, which identifies a file only when nonzero, and `cognitive/builder.py:3116` already had the rule. When a destructive guard rests on a library predicate, read the predicate's source and its fields' documentation, and test the predicate's degenerate input (here, equal zeros) with data that only the precondition's check refuses. (b) A source scan in one milestone's test that names a later milestone's file fails that milestone's focused list on its own, and the assembled tree hides it. Every file a test opens by name exists at the test's own milestone, or the test says why it skips.
**R50.** (Orchestrator, round 4's hardening note; P3, test coverage, not a regression) X17c kills the removal of the index guard (P-44) and of the preflight call (P-45), but not a guard that checks only one of the two indices (it reads 0 for both in X17c) and not a revert of the widened post-marker `except (OSError, SnapshotRefused)` (X17c never reaches it: the name must change after the preflight). Reviewer A's round-4 probes kill both: an asymmetric case (either index 0) and a post-marker case (identity lost after the committed marker: exit 1, no unlink, both names kept, the marker and the first reason retained, the listing says the erasure is unfinished). They are the follow-up that makes P-44 and P-45 exhaustive; reach: a future edit of those two lines.
**R51.** (Orchestrator, round 4; R48's reach, sourced not mounted) A real file system on which `os.link` succeeds and `st_ino` reads 0 has a source-backed example: SSHFS 2.10 over libfuse 2.9.9 with the `use_ino` option against a server that supports the OpenSSH hard-link extension (sshfs-2.10 `sshfs.c` lines 781 to 794 zero-initialize the attributes without filling `st_ino`, and its hard-link operation uses the extension at lines 2305 to 2317; fuse-2.9.9 `lib/fuse.c` lines 1440 to 1443 preserve the supplied inode under `use_ino`). Nobody mounted it. On such a file system an erasure of a snapshot with a temporary name beside it refuses before its marker until the Captain removes that name by hand (R48's fail-closed behaviour); without a temporary name it erases as before.

## 16. Validation of record (2026-10-27, win32)

The same record as `DECISIONS.md`'s *Validation of record* bullet for this slice, with the evidence names (the files folder of the orchestrator's session).

**Mutation campaign.** The 80 rows of section 10, one at a time on the assembled tree (the orchestrator's oracle `m3-h`, tree `e2a036d0794c`: `origin/main` `7cb0b212` plus this contract (A5, with its one-token correction) and the three milestones applied by tool; its code and tests equal the candidate's), whole-line mutation, each row run against the tests it names, pytest without `-x`: **80 of 80 killed**; the unmutated baseline over the four files is 149 passed (`evidence-ad1341s6census-h.txt`; the earlier campaigns: `-final` 49 of 49 on the first candidate, `-d` 69 of 70 with P-8 surviving, `-e` 70 of 70 after A3, `-f` 78 of 78 after A4; `-g` stopped at its premise: the unmutated baseline failed on X17c's mistyped expected value, `(None, None)` for an unmarked row that reads `(None, "")`, corrected by the orchestrator in `277f0333` before `-h`).

**Tests first.** Each new file fails at collection over its milestone's base, in the first build (`evidence-s6bA-*`, `-bB-*`, `-bC-*`) and in the three Builders' rebuild from A2's contract (`evidence-s6bA2-m1-tests-first.txt`, `s6bB2-m2-base`, `s6bC2-m3-tests-first`); each repair's amended files over the previous candidate's source: A2 and A3's fail 21 of 93 cases (`evidence-s6-repair-tf-e.txt`), A4's 10 of 81 (`-f`), A5's 1 of 82 (`-h`).

**Focused lists.** M1 700 passed and 1 skipped, M2 594 and 1, M3 700 and 1, on the assembled candidate `85b943ef` (`evidence-s6-r4-focused-console.txt`, `evidence-s6-r4-m{1,2,3}-focused.txt`); the new files alone 51, 21 and 31 cases. The oracle's lists matched the Architect's analysis at every amendment where they ran (A2: 692, 586, 689; A3: 693, 587, 690; A4: M2 593 and M3 699, M1's list failing at X18 on M1's stage alone, which A5 repaired; A5: 700, 594, 700). The three Builders' rebuild from A2's contract equals the oracle's blobs, 18 of 18 files (M1 against oracle d, M2 and M3 against oracle e: `blob-compare-ad1341s6-m1-d.txt`, `-m2-e`, `-m3-e`); oracle e differs from oracle d only in the contract and in the M1 test file, by A3's change (8 lines inserted, 1 deleted; checked at the M3 stage).

**Review.** M1 to M3 by `gpt-6.1-sol` (`max`) in four rounds (`review-ad1341s6-{a,b,c}-r1.md`, `-r2`, `-r3`, `-a-r4.md`): round 1 all NOT READY, 15 findings (14 repaired by A2 and A3, one recorded as R29); round 2 (the delta of A2 and A3) all NOT READY, four findings (repaired by A4), among them the P1 regression that the Windows-only `stat` attribute broke every full reset, dry run, clean slate and erasure on POSIX; round 3 (the delta of A4) B and C READY, A NOT READY (a file index of 0 taken as proof of identity), repaired by A5 after the Architect's round-three-brake decision (continue); round 4 (the delta of A5, one reviewer) **READY**, with R50 and R51 recorded. Two commit messages (`8421da2e`, `779b3de5`) count 15 findings repaired and one recorded (16); the three reports list 15 (A 8, B 4, C 3), 14 repaired and A-F8 recorded. The Architect decided every amendment and took the brake once; nothing needed the Captain.

**Not verified.** A native Linux or macOS run: the POSIX behaviour is by reading, by a stand-in for the `stat` import at the module boundary and by CPython 3.12.13's source (section 11's POSIX audit); CI's ubuntu shards are the first native run. A complete vessel boot and reset on a real ship. A BagIt validator beyond `zipfile`.
