# AD-1341 S3: the Captain reviews and vetoes what is promoted into the Ship's Archive, and an AD-754 erasure never leaves an archive entry citing an erased episode

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26

**Status:** build-ready. Slice 3 of 6 of #1569; it does not close the issue. No new AD or BF number. **Base (re-anchored by the orchestrator, 2026-10-26):** `origin/main` `2ca3a6ed603013316d65f59a7b80ec30a80be00f`, tree `83711dc2ee9edc59f3786c44e47f6742de50315a`, with S1, BF-925 and S2 merged (S2: `prompts/ad-1341-s2-inherited-label.md`, PR #1682). The Architect drafted this contract on `7bdd9c32` (tree `54c086ffc33b64aa9dbe413575fb3ad89950071e`) against S2's first contract; S2 then took three amendments (A2, A3 and A3c). Every SEARCH block below was applied by tool to the merged base's tree, 36 of 36 pairs (M1 16, M2 7, M3 11, trackers 2), each matching exactly once. The SEARCH blocks, not the line numbers in §0 and §11 (taken on `7bdd9c32`), are what binds, and §0's "S2 overlap" paragraph describes the draft's base, not this one. After the M1 build the orchestrator also corrected §6's first failing import name for M1 (`review_promotion`, not `SourceState`). **Amendment A2 (2026-10-26, round 1 of review: three `gpt-6.1-sol` reviewers, eight findings, no P1).** The citation read answered "nothing cites this" for a cell that is not a JSON list of strings and skipped SQL NULL and empty text (M1-F1, the M1 reviewer; M3-F2, the M3 reviewer, who showed an erasure going through at all three entry points): it now raises (7.1 pairs 5 and 9; V6b, E5, E8; K15, K19 to K23). V7 ran only the veto-first order, and nothing pinned the store lock or the veto's rollback (M1-F3, found first by the orchestrator's census as K4's unkilled claim; M1-F2, the M1 reviewer): V7 runs both orders and V7b pauses and fails a commit (K24 to K26). The M2 tests-first proof accepted an absent command in two cases and nothing protected `pending`'s disabled refusal (M2-F1, M2-F2, the M2 reviewer): C3 asserts its refusal texts, C7 and C-9 are new, and §6's failure locations are corrected. The M3 tests had no attachment store or audit log, so either side effect could move before the refusal (M3-F1, the M3 reviewer): E9, E-6, E-7. A shared attachment blob (M3-F3) and the reviewers' notes are registered (R11 to R15). No pair is added: three REPLACE bodies change (7.1 pairs 5 and 9, 7.6 pair 5; two of the changes are comments that make a mutation anchor unique), with the three new test files. **Captain:** nothing in this slice requires the Captain (D17).

**Milestones and tiers:** M1 the veto record and the two reads (**HIGH**: data integrity, the veto record); M2 the Captain's CLI (**STANDARD**: the Captain's surface over M1's contract); M3 the AD-754 erasure check (**HIGH**: erasure, privacy); M4 trackers. Each milestone is one Builder delegation and one local commit. The broad gate is the orchestrator's single canonical run, once, after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1341-s3 --receipt logs/gates/ad1341-s3.receipt.json`. The Builder runs only the focused gates in §4. Review: cross-family (`gpt-6.1-sol`) for M1 and M3; one round for M2. One mutation campaign, on the assembled tree (§10).

**Tests:** new `tests/test_ad1341_s3_veto_store.py` (M1: 13 functions, 46 cases), `tests/test_ad1341_s3_review_cli.py` (M2: 7 functions, 18 cases), `tests/test_ad1341_s3_erasure_cascade.py` (M3: 9 functions, 24 cases). Updated: `tests/test_ad1341_s1_archive_store.py` (M1: the store's pinned public surface, with an inline reason).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| Promotion is decided in one place: `plan_promotion` applies S1's fixed criteria (D8) and C1 to Ship's Records; `promote_ship_records` writes each record through `promote_entry` | present | `archive_promotion.py:40-66`, `:101-146`, `:149-177` |
| The only caller of the promotion service is `probos reset` (tier 2 and above), after the confirmation and under the AD-816 pidfile; `--dry-run` prints the plan and opens no archive | present | `__main__.py:2974-3007`, `:3276-3318`, `:3321-3354` |
| `promote_entry`'s one statement refuses an erased source (kind and ref, any content) and a duplicate; it then classifies ERASED or PRESENT | present | `archive_store.py:255-265`, `:373-406` |
| No review, no veto and no pending state exists for an archive promotion | present | Absence S3-AV1 |
| The Captain's archive surface is the offline CLI only: `probos archive erase` (`_cmd_archive`); no API route reads or writes the Ship's Archive | present | `__main__.py:3357-3412`, `:3729-3741`; Absence S3-AV2 |
| `erase_entry` is named in `src` only by `__main__.py`; S1's census holds it | present | `__main__.py:3403`; `tests/test_ad1341_s1_reset_and_erase.py:590-601` |
| The AD-754 erasure manager erases episodes and their attachments by id, by resource and by agent; it never reads the Ship's Archive | present | `knowledge/erasure.py:99-233` |
| Its one caller is `POST /api/security/forget`, which has no authorization dependency (only `Depends(get_runtime)`) | present | `routers/security.py:77-106`; Absence S3-AV3 |
| `source_episode_ids` exists on every v1 entry; no `src` producer writes a non-empty list (Ship's Records carry none; lessons are S4) | present | `archive_store.py:61`, `:124`, `:237`; `archive_promotion.py:129-145`; Absence S3-AV4 |
| AD-1340's retention rule for cited episodes is not built (#1568 S5 is held until #1569 S4) | present | #1569 comment 2, P3; Absence S3-AV4 |
| The runtime holds the archive store privately (`_archive_store`) and exposes no accessor | present | `runtime.py:602`, `:1361`, `:2999`; Absence S3-AV5 |
| The route tests build the runtime as a `MagicMock`, so any attribute the route reads by `getattr` is a truthy mock | present | `tests/test_ad1340_s2a_lookup_route.py:200-210`; `tests/test_bf905_erasure_live_scan.py:86-91` |
| The store's public surface is pinned exactly by S1's A7 | present | `tests/test_ad1341_s1_archive_store.py:242-252` |
| The live archive is schema v1 with 0 rows and 0 generations (2026-10-26, read-only) | taken as given | #1569 comment 13; not read here (§Not verified, item 1) |

**S2 overlap.** S2 edits `knowledge/archive_store.py` (the docstring paragraph at `:11-15`; `ArchiveEntry`'s last fields and the `#: AD-1341: the schema` line; `_SQLITE_MAX_ROWID` and `def _valid_reason`; the last lines of `entry_by_id`, `search` and `get_recent`; `_row_to_entry`'s header and its last mapping line), `cognitive/oracle_service.py`, `runtime.py` (the BF-679 block at `:3364-3383`), `PROGRESS.md`'s head and `DECISIONS.md` before the `### Explicit delegation models` heading. S3's anchors in `archive_store.py` are `:3-9`, `:91-92`, `:98-102`, `:226-227`, `:255-265`, `:306-313`, `:386-389`, `:395-406` and `:454-457`, none of which S2 changes; S3 never calls `_row_to_entry` (S2 changes its signature). In `runtime.py` S3 anchors on the `records_store` property (`:2208-2211`). The tracker anchors are the `# ProbOS Progress` title line alone and the `### Explicit delegation models ...` heading alone, both of which S2's REPLACE keeps.

## 1. Problem

#1569 Decision item 6: "The Captain can review and veto promotions. A veto is recorded, and the entry is not written. The archive stays append-only for agents and services. The Captain's erasure right (AD-754) extends to the archive." Its acceptance line: "A Captain veto stops a promotion and is recorded. The Captain's erasure removes an archive entry and leaves an audit marker. No agent or service path updates or deletes an entry."

S1 built the last two halves at the store: `erase_entry` with a content-free marker, reached only from `probos archive erase`, and a census that no other `src` file names it. What remains:

1. **No review and no veto.** The Captain can see the plan only through `probos reset --dry-run`, which does not say what is already archived, and cannot stop one source from being archived except by `--skip-promotion` (all or nothing) or by erasing it afterwards.
2. **AD-754 does not reach the archive.** `ErasureManager` erases episodes and attachments; an archive entry that cites an erased episode (`source_episode_ids`) would keep a curated summary of it after the episode is gone. Today no producer writes a citation (S1 premise P3), so this is latent; S4's lessons cite episodes by design.

## 2. Solution overview

- **M1, the store.** A content-free `archive_vetoes` table (kind, ref, reason, timeline, time; unique per source). `veto_source` records the Captain's veto in one statement and refuses a source already archived or erased. `promote_entry`'s one statement also honours a veto (new outcome `VETOED`). Two reads: `source_state(record)`, what `promote_entry` would do now (the review), and `entry_ids_citing(episode_ids)` (the erasure check). The service reports vetoed sources and gains `review_promotion`.
- **M2, the Captain's CLI.** `probos archive pending` lists every eligible source with what promoting it now would do; `probos archive veto SOURCE_REF --reason TEXT` records a veto. The reset reports how many sources were vetoed; the dry run points to the review.
- **M3, the AD-754 check.** `ErasureManager` reads the open archive and, when an entry cites an episode the request would erase, erases nothing and raises; `POST /api/security/forget` answers 409 with the entry ids. The Captain erases each entry with `probos archive erase` and retries. The runtime gains a read-only `archive_store` accessor.
- **M4.** Trackers.

The default stays as S1 left it: a reset promotes everything eligible that the Captain has not vetoed. No flag, no schema version change, no new event type, no API route for the archive.

## 3. Decisions

- **D1 (premises).** §0. S1's decisions (D3 key, D7 marker, D8 criteria, D12 pidfile, D16 lock) and S2's stand.
- **D2 (what "review before canon" is in S3).** Ranked by what stays inside the delegated-authority envelope:
  - **(A) chosen: opt-out review.** The queue is the plan the next promotion would run; the Captain reviews it (`probos archive pending`, or `reset --dry-run`) and vetoes any source before the reset; the reset promotes everything eligible that is not vetoed. S1's default (promotion before a reset, on by default, Decision item 7) is unchanged, and no reset ever waits for a decision.
  - (B) opt-in approval behind a default-off flag: a source is archived only after the Captain approves it. Deferred to S4. Its consumer is S4's crew-written lessons, which #1569 comment 1 routes through the chain of command; S1's sources are already governed when they are written (AD-551's system convergence, the Captain's own log, `published` status, AD-1140's `claim_id`). At `--full` a pending source would be deleted with Ship's Records (the S6 snapshot is not built), so (B) would have to refuse the reset or lose the source.
  - (C) approval required by default: rejected. It silently weakens S1's default-on promotion and, at `--full`, either blocks the reset or destroys unapproved knowledge. That is the Captain's condition "changing the product objective beyond the existing issue" (Decision item 7) and "an irreversible ... destructive production-data operation"; nothing here needs it.

  Prior art agrees: Wikipedia's pending-changes protection holds edits only from new or unregistered editors for review, while trusted editors' edits go live (§13).
- **D3 (where the queue lives).**
  - **(A) chosen: derived, with no table.** The pending set is `plan_promotion`'s output (S1 D8 and C1), and each source's state is read from the archive's own rows and markers (`source_state`). Nothing is stored twice.
  - (B) a `pending_promotions` table holding title and content: rejected. It is a second copy of content that every erasure would also have to reach, and it goes stale when the document changes.
  - (C) a veto flag in the document's Ship's Records frontmatter: rejected. Agents write Ship's Records, so the flag would be agent-writable, and Ship's Records go at `--full`.
- **D4 (the veto record).**
  - **(A) chosen:** a row in `archive_vetoes` holding the source kind, source ref, the Captain's reason (1–500 characters, stripped), the timeline it was vetoed in (the instance id, or `""`) and the time. It never holds a title, content, metadata or hash. A unique index on `(source_kind, source_ref)` makes one veto per source. It blocks the source with any content, as S1 D7's erasure marker does. The record is kept: as the governed-memory study puts it, "rejected candidates ... are evidence that selection occurred" (§13).
  - (B) key the veto by content hash: rejected. A one-character edit would evade it, and the hash of short content can be guessed (S1 D7 C).
  - (C) reuse `archive_erasures` with no entry: rejected. `entry_id` is `NOT NULL`, S1's marker tests pin that table's shape, and one table would carry two meanings.
- **D5 (what a veto does and refuses).** `veto_source` is one `INSERT … SELECT … WHERE NOT EXISTS … ON CONFLICT DO NOTHING` statement under `_write_lock` (S1 D16). It returns `RECORDED`; `ARCHIVED`, writing nothing, when any entry from the source is archived (a veto does not remove an entry; `erase_entry` does, so each verb keeps one meaning); `ERASED`, writing nothing, when the Captain erased the source (it is already never promoted again); `ALREADY_VETOED` for a second veto, which keeps the first reason. A veto cannot be lifted in S3 (register R4). A revision of an archived source cannot be vetoed while the entry stands (ARCHIVED): the Captain erases the entry, which stops the source with any content (register R15).
- **D6 (promotion honours a veto; one rule for two reads).** `_PROMOTE_SQL` adds `AND NOT EXISTS` on `archive_vetoes` to its one statement, so a veto can never land between a check and the insert. After a refused insert the classification order is erased, then vetoed, then present. `source_state` runs the same checks in the same order and returns `CREATED` when none holds, with the ids already archived from the source. It is a read with no lock, so a veto or erasure after the review decides the promotion: the review is not a reservation. Tested both ways (§6, V5 and V5b): the two agree in every state, and a veto or erasure between them decides the promotion.
- **D7 (schema).**
  - **(A) chosen:** `archive_vetoes` and its index are added to `_SCHEMA` with `IF NOT EXISTS`, so every open creates them; `user_version` stays 1. A v1 file written before S3 gains the table on its next open, with every row kept (V1).
  - (B) bump to v2: rejected. A revert to S1's code would refuse a v2 file, and S1 refuses every tier 2 reset when the archive cannot open (S1 R3): a revert would block resets. With (A) a revert only stops honouring vetoes (*Reversal* in §8).
- **D8 (the AD-754 cascade).** Ranked:
  - **(A) chosen: refuse first.** When an archive entry cites an episode an AD-754 request would erase, the manager erases nothing and raises `ArchiveCitationsBlockErasure` with those entry ids; the route answers 409 `archive_entries_cite_erased_episodes` with the ids. The Captain erases each entry with `probos archive erase ENTRY_ID --reason TEXT` (S1's Captain-only path, with its marker) and retries. Nothing is silently left behind, and the archive gains no new deleter.
  - (B) the manager erases the citing entries itself: rejected. `/forget` has no authorization and ships with an empty crew-scope token (open by default), so the archive would gain a deleter that any local caller can reach, against "no agent or service path deletes an entry".
  - (C) cascade only when a crew-scope token is configured and presented: deferred. It needs `/forget`'s authorization changed (a tightening with its own consumers: the AD-1340 S2a and S2b seam tests post to it without the header) and a second deleter of entries. It can be added on top of (A) later (register R1).
  - (D) erase the episodes and keep the entries: rejected. A curated summary would outlive its erased evidence, and an agent or resource retry could never find those episodes again to report them.
- **D9 (which entries an erasure reaches).** Citations only: an entry whose `source_episode_ids` names an episode the request matched. Not by author: AD-754 does not erase an agent's Ship's Records either, records-sourced entries carry no `author_did`, and callsigns repeat across generations (S2's RS2-3). Not by `source_ref`, which is a records path, not an AD-754 key. Not by content match, which would erase curated culture on a substring. Not by `classification`, which is `ship` or `fleet` on every entry. Any entry can still be erased by id (S1). The test proves that an entry authored by the agent and citing nothing does not block that agent's erasure (E3).
- **D10 (order and failure).** The check runs before anything is erased: for one episode, before its attachments; for a resource or an agent, after the scan and before `_forget_all`. Each per-episode erase checks again, so a citation that lands after the scan still stops that episode (E8). A failed read propagates with nothing erased: the store closed, or any citation cell that is not a JSON list of strings (malformed JSON, an object, a string, a number, `null`, a list holding a non-string, empty text or SQL NULL), which the read refuses and never answers "none" for (V6b, E5; a cell that becomes unreadable after the scan fails every per-episode erase, E8). "Before anything is erased" covers the matched episodes, their own attachments and the audit marking (E9); an attachment blob another episode also references is unlinked as before S3 (register R11). With no open archive (disabled, failed at boot, or closed at shutdown) there is nothing to check, and the erasure proceeds as before (E4; register R2).
- **D11 (AD-1340's retention rule).** Retention, when #1568 S5 builds it, protects a cited episode from decay and eviction, never from the Captain's erasure. Under D8 no archive entry ever cites an erased episode, so S5 may rely on that.
- **D12 (authority).** A veto and an erasure of an entry are the Captain's, through the operator's shell, as S1 decided. The censuses: `veto_source` is named in `src` only by `__main__.py` (C6); `erase_entry` still only by `__main__.py` (E6, S1's R11 unchanged); `entry_ids_citing` only by `knowledge/erasure.py`; `ErasureManager` is built only by `routers/security.py` (E6); `source_state` only by the review service (V10). The route only refuses.
- **D13 (audit).** The `archive_vetoes` and `archive_erasures` rows are the audit of record (content-free). Each veto logs a WARNING naming the source kind; a refused erasure logs a WARNING with the count. No `EventType`: the CLI runs offline with no event bus, and AD-754's manager emits none today. `generations` gains no vetoed count (register R9).
- **D14 (`probos reset`).** Unchanged in flow. Its promotion message adds "N vetoed by the Captain". The dry run adds one line pointing to `probos archive pending` and `probos archive veto`; S1's plan lines are kept byte for byte (`tests/test_ad1341_s1_reset_and_erase.py:479`).
- **D15 (the Captain's surface).** CLI only, beside `probos archive erase`. No API route: since S1 the archive's Captain controls are the offline CLI, and no route reads the archive. An HXI view is later work.
- **D16 (tiers).** M1 HIGH, M2 STANDARD, M3 HIGH (status line).
- **D17 (the Captain).** Nothing here meets a "Still requires the Captain" condition. D2 (C) would (it changes the product objective of Decision item 7), and it is rejected. Tightening `/forget`'s authorization is deferred, not decided (D8 C).
- **D18 (not built).** S4: the lessons format, the stand-down and its exit-notes turn, and chain-of-command review (D2 B). S5: after-action triggers and continuous promotion. S6: the `--full` snapshot, the nature "description entry" and `--clean-slate`. Also not built: lifting a veto, a bulk erase, an archive listing by id, authorization on `/forget`, and an HXI view (register).

**Disclosed effects.**
1. Every archive open creates `archive_vetoes` and its index if absent (additive; `user_version` stays 1). The live archive gains the table on the first boot after merge.
2. `promote_entry` can return `VETOED`; `PromotionReport` gains `vetoed` (defaulted).
3. The reset's promotion line reads "…, N erased by the Captain, N vetoed by the Captain, N withheld …"; the dry run prints one more line when anything is eligible.
4. `probos archive pending` and `probos archive veto` open the configured archive through `initialize()`, as `erase` does: a missing archive file is created empty at v1 (S1's RA1-3 parity).
5. An AD-754 erasure (`POST /api/security/forget`) whose matched episodes an archive entry cites erases nothing and answers 409. Until S4 produces citations no entry cites an episode, so nothing changes in practice.
6. With the archive enabled but unavailable (failed at boot, or closed at shutdown) an AD-754 erasure proceeds without the check (register R2).

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write each milestone's new test file first and run it on the milestone's base: it must fail at import (the first new name it imports), and then each test must fail at the assertion §6 names once the names exist but the behaviour is the base's. If a test outside §7 fails, stop and report it; never delete or loosen a test.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** the veto record and the reads | HIGH | 7.1 `src/probos/knowledge/archive_store.py`; 7.2 `src/probos/knowledge/archive_promotion.py`; 7.3 `docs/development/store-baseline.yaml`; 7.4 `tests/test_ad1341_s1_archive_store.py`; 7.5 new `tests/test_ad1341_s3_veto_store.py` | `tests/test_ad1341_s3_veto_store.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s2_inherited_label.py tests/test_ad524_ships_archive.py tests/test_bf919_archive_isolation.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1256_store_registry.py tests/test_ad1265_backup_coverage.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` |
| **M2** the Captain's CLI | STANDARD | 7.6 `src/probos/__main__.py`; 7.7 new `tests/test_ad1341_s3_review_cli.py` | `tests/test_ad1341_s3_review_cli.py tests/test_ad1341_s3_veto_store.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s2_inherited_label.py tests/test_reset_integration.py tests/test_distribution.py tests/test_proactive.py tests/test_identity_deterministic.py tests/test_ad1340_s1_restore_reset.py tests/test_bf902_fts_reconciliation.py tests/test_bf892_spawn_env_guard.py tests/test_quality_hardening.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M3** the AD-754 check | HIGH | 7.8 `src/probos/knowledge/erasure.py`; 7.9 `src/probos/routers/security.py`; 7.10 `src/probos/runtime.py`; 7.11 new `tests/test_ad1341_s3_erasure_cascade.py` | `tests/test_ad1341_s3_erasure_cascade.py tests/test_ad1341_s3_veto_store.py tests/test_erasure_manager.py tests/test_ad1340_s1_erasure.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_bf905_erasure_live_scan.py tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2b_restore_route.py tests/test_ad1025b_path_anchoring.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad680_public_runtime_api.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M4** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

If S2 has not merged when M1 starts, drop `tests/test_ad1341_s2_inherited_label.py` from the gates and say so in the build report (S2 merges first by plan).

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `archive_vetoes` table and unique index | `ArchiveStore` (its writer and readers); `docs/development/store-baseline.yaml` rule 11 (7.3); `scripts/check_store_registry.py --check`; `tests/test_ad1256_store_registry.py`; the AD-1265 archive backup root (online backup copies every table) | registry row updated; backup unchanged in shape |
| `PromotionOutcome.VETOED` | `promote_ship_records` (its one consumer in `src`: Absence S3-AV6); tests comparing outcomes by identity | a vetoed source is reported as vetoed, never as present |
| `PromotionReport.vetoed` (defaulted) | `__main__._promote_into_archive` (the message); `tests/test_ad1341_s1_promotion.py:256` compares a whole report with four keyword fields, which the default keeps equal | message gains the count |
| `veto_source`, `source_state`, `entry_ids_citing` | M2's CLI (`veto_source`), `review_promotion` (`source_state`), M3's manager (`entry_ids_citing`); S1's A7 pin (7.4) | new; censuses V10, C6, E6. A2: `entry_ids_citing` raises `ValueError` for any fetched cell that is not a JSON list of strings, and `_CITING_SQL` skips only `'[]'`; its one consumer, `_refuse_while_the_archive_cites`, propagates it, and `_forget_all` records it per episode (E5, E8) |
| `VetoOutcome`, `SourceState` | M2's CLI, the review service | new |
| `review_promotion`, `PromotionReview`, `PendingSource` | M2's `probos archive pending` | new |
| `_PROMOTE_SQL` gains a veto check and two parameters | `promote_entry` only | refuses a vetoed source |
| reset promotion message | the Captain's terminal; no test pins its text (Absence S3-AV7) | one more count |
| dry-run hint line | the Captain's terminal; `test_ad1341_s1_reset_and_erase.py:479-480` asserts other lines, kept | one more line |
| `_cmd_archive` dispatch (`pending`, `veto`) | `main` (`sys.exit(_cmd_archive(args))`, `__main__.py:3802-3804`); S1's `_erase` helper (`archive_cmd="erase"`) | erase unchanged |
| `ErasureManager(..., *, archive_store=None)` | `routers/security.py:83` (its one `src` builder, Absence S3-AV3); tests build it positionally with three arguments | default None keeps every caller |
| `ArchiveCitationsBlockErasure` | `request_erasure` (409); `_forget_all` counts it as a per-episode failure when a citation lands mid-run | new |
| `POST /api/security/forget` 409 | no HXI or CLI caller (Absence S3-AV3); the AD-1340 seam tests (no citing entry: unchanged) | new answer |
| `ProbOSRuntime.archive_store` (read-only property) | `request_erasure` (`getattr`, accepting only a real `ArchiveStore`); shutdown still clears `_archive_store` (`startup/shutdown.py:2064-2074`) | new public read |

## 6. Tests

On each milestone's base, every test in its new file fails at import or at its first assertion (M1: `ImportError: cannot import name 'review_promotion'`, the first new name in the file's import order, because it imports `archive_promotion` before `archive_store`, so the file cannot run against §7.1 alone and needs §7.2 before it imports; M2: the M2 file imports M1's test module, which imports after M1, and then each of its 18 cases fails at an assertion; M3: `ImportError: cannot import name 'ArchiveCitationsBlockErasure'`, and with that name and the `archive_store` keyword made compatible and no check, 19 of its 24 cases fail while E3 (3) and E4 (2) pass, as controls). **What tests first can show for M2 (A2, M2-F1).** On the M1 base `_cmd_archive` answers every sub-command but `erase` with its usage line and exit 2 (`072adb71:src/probos/__main__.py:3367-3369`), so a case whose expected exit is 2 cannot fail on its exit code: C3 `[blank-reason]`, C3 `[disabled]` and C7 each assert their own refusal text, which the usage line does not contain, and fail there. Tests first therefore shows that the two commands are absent; it cannot show which guard refuses, and the census does (C-2 to C-4, C-6, C-9). C2 fails at its first assertion (its first `pending`) and C3 `[again]` at its arranging veto, before the assertions that are their point. The last column names the assertion that fails once the names exist but the behaviour is the base's. It is the Architect's analysis, not a Builder's run for M1 (round 1's reviewers ran M2's and M3's: before A2, 15 of 17 M2 cases failed, the two C3 cases above passing, and 10 of 15 M3 cases, with E3 and E4 as controls), and the evidence that each test discriminates is the orchestrator's mutation census (§10).

**M1, `tests/test_ad1341_s3_veto_store.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| V1 | `test_the_archive_has_a_content_free_veto_table_keyed_by_source[fresh, s1-file]` | D4, D7: six columns; a UNIQUE index on `(source_kind, source_ref)`; `user_version` 1; an S1-era v1 file gains it with its rows kept | `PRAGMA table_info(archive_vetoes)` columns (base: no table; `[s1-file]` fails earlier at its `DROP TABLE`) |
| V2 | `test_a_vetoed_source_is_never_archived_with_any_content[same-content, revised-content, next-timeline]` | D4, D6: RECORDED; then VETOED for the source with any content and any timeline; one marker of the fixed shape, reason and timeline stripped | `promote_entry(later) is PromotionOutcome.VETOED` (base: CREATED) |
| V3 | `test_a_veto_that_would_change_nothing_writes_nothing[archived, erased, again]` | D5: ARCHIVED, ERASED, ALREADY_VETOED; no row written; a second veto keeps the first reason | `veto_source(...) is expected` |
| V4 | `test_a_veto_needs_a_kind_a_source_and_a_reason[str-kind, blank-ref, int-ref, blank-reason, long-reason, int-timeline]` | exact types; ValueError; nothing written | `pytest.raises(ValueError)` |
| V5 | `test_the_review_reads_what_promote_entry_then_does[new, present, revised, erased, vetoed]` | D6, one rule for both reads: `source_state` equals the expected state, writes nothing, and `promote_entry` then returns the same outcome | `preview == expected` |
| V5b | `test_a_veto_or_erasure_after_the_review_decides_the_promotion[veto, erasure]` | D6, the case that changes the state between the two reads: the review says CREATED, a veto or erasure lands, and the promotion is refused | `promote_entry(record) is expected` |
| V6 | `test_the_entries_citing_an_episode_are_found_in_id_order[one, two-in-id-order, none, blank-ignored, empty, tuple]` | D9: ids ascending; AD-524 rows and uncited entries never match; blank ids ignored; nothing written | `found == ...` |
| V6b | `test_the_citation_read_never_answers_none_when_it_cannot_read[not-open, a-string, corrupt-row, dict, dict-key, string, number-list, mixed-list, number, json-null, empty-text, sql-null]` | D10: RuntimeError, TypeError, then ValueError for every cell that is not a JSON list of strings (an object, a string, a list holding a number, a number, `null`, empty text, and SQL NULL on an AD-524 file whose citation column was added nullable); never `()` and never a match read from an object's keys | `pytest.raises(RuntimeError)` |
| V7 | `test_a_veto_and_a_promotion_of_one_source_never_both_succeed[veto, promotion]` | D5, D6 under S1 D16: `gather` starts its tasks in order, so each order runs deterministically and ends as it must: veto first, RECORDED then VETOED; promotion first, CREATED then ARCHIVED | the outcome-and-count tuple |
| V7b | `test_a_write_whose_commit_fails_leaves_nothing_the_other_write_can_commit[veto-fails, promotion-fails]` | S1 D16 for the S3 writes: the first write's commit pauses, then fails; the second waits on the lock and, after the rollback, runs as if the first never happened (promotion CREATED; veto RECORDED) | `store.veto_source` (base: `AttributeError`) |
| V8 | `test_the_promotion_reports_a_vetoed_source_and_archives_the_rest` | the service: `vetoed` holds the source; the rest promoted; no row for it | `report.vetoed == (_CONVERGENCE,)` |
| V9 | `test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing` | the review over real Ship's Records: revised (with the entry it revises), present, erased, vetoed, new, withheld; the archive's row counts unchanged | `states == {...}` |
| V10 | `test_only_the_review_reads_what_a_promotion_would_do` | census: `source_state` named in `src` only by `knowledge/archive_promotion.py` | `_naming(...) == {...}` |

**M2, `tests/test_ad1341_s3_review_cli.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| C1 | `test_pending_shows_what_the_next_promotion_would_do_with_each_source` | `probos archive pending` over the V9 scene: the header, one line per state with entry ids, the withheld line; exit 0; the archive's counts unchanged | `_archive(..., "pending") == 0` (base: 2, usage) |
| C2 | `test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew` | **the real seam:** pending, then the Captain's veto, then a real tier 2 reset ("1 vetoed by the Captain"), then the next crew revises the report and resets again; never archived; the generations rows; a later crew's real Oracle never returns it; pending shows it vetoed | `_archive(..., "pending") == 0`, its first assertion (base: 2, the usage line) |
| C3 | `test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing[not-eligible, withheld, archived, erased, again, blank-reason, declined, disabled]` | exit 1, 1, 1, 0, 0, 2, 0, 2; no veto row beyond the first; `[blank-reason]` and `[disabled]` print the veto's own refusal, which the usage line does not contain | the exit code; `[again]` at its arranging veto; `[blank-reason]` and `[disabled]` at the refusal text (base: the usage line, exit 2) |
| C4 | `test_main_dispatches_pending_and_veto_with_the_captains_options[pending, pending-root-data-dir, veto, veto-root-config, veto-own-data-dir]` | the parser, with S1 D19's SUPPRESS rule | `SystemExit` code 3 (base: argparse exits 2) |
| C5 | `test_the_dry_run_points_the_captain_to_the_review` | D14: the hint; S1's plan line kept; no archive file | `"probos archive pending" in out` |
| C6 | `test_only_the_cli_vetoes_a_source` | census: `veto_source` named only by `__main__.py` | `_naming("veto_source") == {"__main__.py"}` (after M1: empty set) |
| C7 | `test_pending_refuses_a_disabled_archive_and_creates_no_file` | disclosed effect 4's limit: with the archive disabled, `pending` exits 2 with its own diagnostic and creates no archive file | the refusal text (base: the usage line, exit 2, no file) |

**M3, `tests/test_ad1341_s3_erasure_cascade.py`:**

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| E1 | `test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing[episode, agent, resource]` | D8, D10: a real `EpisodicMemory` and archive; the manager raises with the citing entry's id; both episodes stay live; the archive unchanged | `pytest.raises(ArchiveCitationsBlockErasure)` |
| E2 | `test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes[episode, agent]` | **the real seam:** the real app's `/forget` answers 409 with the id and erases nothing; the Captain's real `probos archive erase` erases the entry with its marker; the retry answers 200 and erases the episodes; the uncited entry is kept | `refused.status_code == 409` (base: 200) |
| E3 | `test_an_erasure_no_archive_entry_cites_erases_as_before[episode, agent, resource]` | D9: an entry citing another episode, and one authored by the agent that cites nothing, block nothing | (passes on the base once the keyword exists: the control) |
| E4 | `test_the_forget_route_consults_only_a_real_archive_store[mock, none]` | D10: a runtime double's `MagicMock` attribute, or None, is no archive; the erasure proceeds | `erased.status_code == 200` (fails only if the route passes a non-store) |
| E5 | `test_an_archive_that_cannot_answer_stops_the_erasure_before_anything_is_erased[closed, corrupt-row, dict, string, dict-agent, dict-resource]` | D10: the failed read propagates at each entry point, an object or a string cell included; both episodes live | `pytest.raises((RuntimeError, ValueError))` |
| E6 | `test_only_the_erasure_manager_reads_citations_and_only_the_forget_route_builds_it` | D12: `entry_ids_citing` only in `knowledge/erasure.py`; `ErasureManager(` only in `routers/security.py`; `erase_entry` still only `__main__.py` | `_naming("entry_ids_citing") == {...}` |
| E7 | `test_the_runtime_exposes_its_archive_store_read_only` | a property with no setter, returning `_archive_store` | `isinstance(accessor, property)` (base: `AttributeError`) |
| E8 | `test_a_citation_that_appears_after_the_scan_still_stops_that_episode[citation, unreadable-cell]` | D10, the case that changes the citations between the two reads: a promotion citing an episode lands after the scan's check; that episode is refused, the other erased, and `ErasureCascadeIncomplete` names it; `[unreadable-cell]`: the landed entry's cell becomes an object, and every per-episode check fails with nothing erased | `pytest.raises(ErasureCascadeIncomplete)` |
| E9 | `test_a_refused_erasure_keeps_the_cited_episodes_attachment_and_audit_row[episode, agent, resource, late]` | D10, §14 property 5: a real `FilesystemAttachmentStore` and a real `AuditLog`; a refusal at each entry point, and at the per-episode check (`[late]`), leaves the cited episode, its attachment and its audit row | `pytest.raises(ArchiveCitationsBlockErasure)` (`[late]`: `ErasureCascadeIncomplete`) |

**How each decision is tested:** D2 by C2; D3 by V9 and C1; D4 by V1, V2; D5 by V3, V7, V7b, C3; D6 by V5 and V5b (the state changes between the review and the promotion); D7 by V1 `[s1-file]`; D8 by E1, E2; D9 by E3 and V6; D10 by V6b, E4, E5, E8 (the citations change between the scan's check and the per-episode check) and E9 (the attachments and audit rows); D12 by V10, C6, E6; D13 by V2's marker and C2's reason; D14 by C2, C5; D15 by C4, C7.

## 7. The contract

### 7.1 `src/probos/knowledge/archive_store.py` (M1)

Pair 1 (the module docstring; S2's pair 1 edits the next paragraph, not this one):

SEARCH:
```python
Stores curated knowledge entries that survive resets. Agents and services never
update or delete an entry. The one write is ``ArchiveStore.promote_entry``
(AD-1341), called only by the promotion service
(``probos.knowledge.archive_promotion``); it is idempotent on the source and its
content. The one removal is the Captain's ``erase_entry``, reached only from the
offline ``probos archive erase``: it deletes the row and leaves a marker in
``archive_erasures`` that holds no title, content or hash.
```
REPLACE:
```python
Stores curated knowledge entries that survive resets. Agents and services never
update or delete an entry. The one write is ``ArchiveStore.promote_entry``
(AD-1341), called only by the promotion service
(``probos.knowledge.archive_promotion``); it is idempotent on the source and its
content. The one removal is the Captain's ``erase_entry``, reached only from the
offline ``probos archive erase``: it deletes the row and leaves a marker in
``archive_erasures`` that holds no title, content or hash.

AD-1341 S3: the Captain reviews what the next promotion would archive
(``source_state``, through ``probos archive pending``) and may veto a source
before it is archived (``veto_source``, through ``probos archive veto``): a row
in ``archive_vetoes`` that holds no title, content or hash, and that
``promote_entry`` honours for the source with any content. The AD-754 erasure
manager reads ``entry_ids_citing`` and erases nothing while an entry cites an
episode it would erase, until the Captain has erased that entry.
```

Pair 2 (the new promotion outcome):

SEARCH:
```python
    PRESENT = "present"  # this source with this content is already archived
    ERASED = "erased"  # the Captain erased this source; it is not archived again
```
REPLACE:
```python
    PRESENT = "present"  # this source with this content is already archived
    ERASED = "erased"  # the Captain erased this source; it is not archived again
    VETOED = "vetoed"  # AD-1341 S3: the Captain vetoed this source before it was archived; it never is
```

Pair 3 (the veto's outcome and the review's state):

SEARCH:
```python
    PROMOTED = "promoted"
    SKIPPED = "skipped"


def _required_text(value: object, name: str) -> None:
```
REPLACE:
```python
    PROMOTED = "promoted"
    SKIPPED = "skipped"


class VetoOutcome(StrEnum):
    """AD-1341 S3: what ``veto_source`` did with the Captain's veto of a source."""

    RECORDED = "recorded"
    ALREADY_VETOED = "already_vetoed"  # a veto of this source is recorded already; the first reason stands
    ARCHIVED = "archived"  # an entry from this source is archived: a veto does not remove it, erase_entry does
    ERASED = "erased"  # the Captain erased this source's entry, so it is already never promoted again


@dataclass(frozen=True)
class SourceState:
    """AD-1341 S3: what ``promote_entry`` would do with a record now, and the ids already archived from its source.

    ``outcome`` is CREATED when the record would be archived (new, or a revision of the entries in ``entry_ids``).
    Read with no lock: a veto, erasure or promotion after the read decides what ``promote_entry`` does. The review is
    not a reservation.
    """

    outcome: PromotionOutcome
    entry_ids: tuple[int, ...] = ()


def _required_text(value: object, name: str) -> None:
```

Pair 4 (the veto table):

SEARCH:
```python
CREATE INDEX IF NOT EXISTS idx_archive_erasures_source ON archive_erasures(source_kind, source_ref);
"""
```
REPLACE:
```python
CREATE INDEX IF NOT EXISTS idx_archive_erasures_source ON archive_erasures(source_kind, source_ref);

CREATE TABLE IF NOT EXISTS archive_vetoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    vetoed_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_vetoes_source ON archive_vetoes(source_kind, source_ref);
"""
```

Pair 5 (the one write honours a veto; the veto's statement and the reads' statements):

SEARCH:
```python
# One statement, so an erasure can never land between a check and the insert.
_PROMOTE_SQL = (
    "INSERT INTO archive (timeline_id, category, title, content, author_agent_type, author_callsign, "
    "archived_at, metadata, source_kind, source_ref, content_sha256, classification, author_did, "
    "source_episode_ids) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
    "WHERE NOT EXISTS (SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ?) "
    f"ON CONFLICT ({_PROMOTION_KEY}) WHERE content_sha256 IS NOT NULL DO NOTHING"
)

_ERASED_SOURCE_SQL = "SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ? LIMIT 1"
```
REPLACE:
```python
# One statement, so neither an erasure nor (AD-1341 S3) a veto can land between a check and the insert.
_PROMOTE_SQL = (
    "INSERT INTO archive (timeline_id, category, title, content, author_agent_type, author_callsign, "
    "archived_at, metadata, source_kind, source_ref, content_sha256, classification, author_did, "
    "source_episode_ids) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
    "WHERE NOT EXISTS (SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ?) "
    "AND NOT EXISTS (SELECT 1 FROM archive_vetoes WHERE source_kind = ? AND source_ref = ?) "
    f"ON CONFLICT ({_PROMOTION_KEY}) WHERE content_sha256 IS NOT NULL DO NOTHING"
)

_ERASED_SOURCE_SQL = "SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ? LIMIT 1"

# AD-1341 S3 (D6): the Captain's veto, honoured by promote_entry and shown by source_state.
_VETOED_SOURCE_SQL = "SELECT 1 FROM archive_vetoes WHERE source_kind = ? AND source_ref = ? LIMIT 1"

_PRESENT_SQL = "SELECT 1 FROM archive WHERE source_kind = ? AND source_ref = ? AND content_sha256 = ? LIMIT 1"

_SOURCE_ENTRIES_SQL = "SELECT id FROM archive WHERE source_kind = ? AND source_ref = ? ORDER BY id"

# AD-1341 S3 (D5): one statement. A source already archived or erased is refused, and a second veto writes nothing.
_VETO_SQL = (
    "INSERT INTO archive_vetoes (timeline_id, source_kind, source_ref, reason, vetoed_at) "
    "SELECT ?, ?, ?, ?, ? "
    "WHERE NOT EXISTS (SELECT 1 FROM archive AS a WHERE a.source_kind = ? AND a.source_ref = ?) "
    "AND NOT EXISTS (SELECT 1 FROM archive_erasures AS e WHERE e.source_kind = ? AND e.source_ref = ?) "
    "ON CONFLICT (source_kind, source_ref) DO NOTHING"
)

# AD-1341 S3 (D9, D10): every entry whose citation cell is not the canonical '[]' (AD-524 rows and uncited entries hold
# it). SQL NULL and empty text are fetched, so that entry_ids_citing refuses them instead of skipping them.
_CITING_SQL = "SELECT id, source_episode_ids FROM archive WHERE source_episode_ids IS NOT '[]' ORDER BY id"
```

Pair 6 (the class docstring):

SEARCH:
```python
    """The Ship's Archive (AD-524), with AD-1341's provenance, promotion and the Captain's erasure.

    Agents and services never update or delete an entry: ``promote_entry`` is the one write and
    ``erase_entry`` the one removal (Captain-only, through ``probos archive erase``). Uses the
    ConnectionFactory protocol for cloud-ready storage.

    AD-1341 A2 (F1): one connection serves every call, and a ROLLBACK or COMMIT ends whatever that connection
    has open. So the three writes and ``close`` hold ``_write_lock`` from their first statement through the
```
REPLACE:
```python
    """The Ship's Archive (AD-524), with AD-1341's provenance, promotion, and the Captain's veto and erasure.

    Agents and services never update or delete an entry: ``promote_entry`` is the one write of an entry and
    ``erase_entry`` the one removal (Captain-only, through ``probos archive erase``). ``veto_source`` (S3) records
    the Captain's veto of a source (Captain-only, through ``probos archive veto``); it writes no entry. Uses the
    ConnectionFactory protocol for cloud-ready storage.

    AD-1341 A2 (F1): one connection serves every call, and a ROLLBACK or COMMIT ends whatever that connection
    has open. So the four writes and ``close`` hold ``_write_lock`` from their first statement through the
```

Pair 7 (the write's parameters):

SEARCH:
```python
            record.content_sha256, record.classification, record.author_did,
            json.dumps(list(record.source_episode_ids)), kind, record.source_ref,
        )
```
REPLACE:
```python
            record.content_sha256, record.classification, record.author_did,
            json.dumps(list(record.source_episode_ids)), kind, record.source_ref,
            kind, record.source_ref,  # AD-1341 S3: the veto check
        )
```

Pair 8 (the write's classification):

SEARCH:
```python
                created = cursor.rowcount == 1
                erased = False
                if not created:
                    cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, record.source_ref))
                    erased = await cursor.fetchone() is not None
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        if created:
            return PromotionOutcome.CREATED
        return PromotionOutcome.ERASED if erased else PromotionOutcome.PRESENT
```
REPLACE:
```python
                created = cursor.rowcount == 1
                erased = vetoed = False
                if not created:  # AD-1341 S3 (D6): erased, then vetoed, then present; source_state reads the same
                    cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, record.source_ref))
                    erased = await cursor.fetchone() is not None
                    cursor = await self._db.execute(_VETOED_SOURCE_SQL, (kind, record.source_ref))
                    vetoed = await cursor.fetchone() is not None
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        if created:
            return PromotionOutcome.CREATED
        if erased:
            return PromotionOutcome.ERASED
        return PromotionOutcome.VETOED if vetoed else PromotionOutcome.PRESENT
```

Pair 9 (the veto and the two reads, after `erase_entry`; S2's pair 4 edits only `entry_by_id`'s last three lines):

SEARCH:
```python
        logger.warning("AD-1341: the Captain erased Ship's Archive entry %d", entry_id)
        return True

    async def entry_by_id(self, entry_id: int) -> ArchiveEntry | None:
```
REPLACE:
```python
        logger.warning("AD-1341: the Captain erased Ship's Archive entry %d", entry_id)
        return True

    async def veto_source(
        self, source_kind: SourceKind, source_ref: str, reason: str, *, timeline_id: str = "",
    ) -> VetoOutcome:
        """AD-1341 S3: the Captain's veto of a source before it is archived, reached only from ``probos archive veto``.

        One statement (``_VETO_SQL``) writes a row in ``archive_vetoes``: the source kind and ref, the Captain's
        reason, the timeline it was vetoed in and the time; never a title, content, metadata or hash.
        ``promote_entry`` then refuses the source with any content (VETOED). Nothing is written for a source an entry
        is archived from (ARCHIVED: a veto does not remove an entry, ``erase_entry`` does), for a source the Captain
        erased (ERASED: it is never promoted again already), or for a second veto (ALREADY_VETOED: the first reason
        stands). Holds ``_write_lock`` through the commit or rollback (S1 D16).
        """
        if type(source_kind) is not SourceKind:
            raise ValueError("AD-1341: source_kind must be a SourceKind")
        _required_text(source_ref, "source_ref")
        text = _valid_reason(reason)
        if type(timeline_id) is not str:
            raise ValueError("AD-1341: timeline_id must be a string")
        kind = source_kind.value
        params = (timeline_id.strip(), kind, source_ref, text, time.time(), kind, source_ref, kind, source_ref)
        async with self._write_lock:  # AD-1341 S3: the veto and its checks commit or roll back alone (D16)
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_VETO_SQL, params)
                recorded = cursor.rowcount == 1
                archived = was_erased = False
                if not recorded:
                    cursor = await self._db.execute(_SOURCE_ENTRIES_SQL, (kind, source_ref))
                    archived = await cursor.fetchone() is not None
                    cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, source_ref))
                    was_erased = await cursor.fetchone() is not None
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)  # AD-1341 S3: nothing is left open for the next write
                raise
        if recorded:
            logger.warning("AD-1341 S3: the Captain vetoed a %s source's promotion into the Ship's Archive", kind)
            return VetoOutcome.RECORDED
        if archived:
            return VetoOutcome.ARCHIVED
        return VetoOutcome.ERASED if was_erased else VetoOutcome.ALREADY_VETOED

    async def source_state(self, record: PromotionRecord) -> SourceState:
        """AD-1341 S3: what ``promote_entry`` would do with ``record`` now, and the ids archived from its source.

        The same checks in the same order as ``promote_entry`` (an erasure, then a veto, then this content already
        archived), CREATED when none holds (D6). A read: no lock and no commit (S1 D16), so a later write decides.
        """
        if type(record) is not PromotionRecord:
            raise TypeError("AD-1341: source_state takes a PromotionRecord")
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")
        kind, ref = record.source_kind.value, record.source_ref
        cursor = await self._db.execute(_SOURCE_ENTRIES_SQL, (kind, ref))
        entry_ids = tuple(row[0] for row in await cursor.fetchall())
        cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, ref))
        if await cursor.fetchone() is not None:
            return SourceState(PromotionOutcome.ERASED, entry_ids)
        cursor = await self._db.execute(_VETOED_SOURCE_SQL, (kind, ref))
        if await cursor.fetchone() is not None:
            return SourceState(PromotionOutcome.VETOED, entry_ids)
        cursor = await self._db.execute(_PRESENT_SQL, (kind, ref, record.content_sha256))
        present = await cursor.fetchone() is not None
        return SourceState(PromotionOutcome.PRESENT if present else PromotionOutcome.CREATED, entry_ids)

    async def entry_ids_citing(self, episode_ids: list[str] | tuple[str, ...]) -> tuple[int, ...]:
        """AD-1341 S3: the ids of the entries whose ``source_episode_ids`` name any of ``episode_ids``, ascending.

        The AD-754 erasure manager's check (``knowledge/erasure.py``): an episode an entry cites is not erased until
        the Captain has erased the entry (D8). Blank ids match nothing. A read, with no lock (S1 D16). It raises when
        the store is not open, and ``ValueError`` when any citation cell is not a JSON list of strings (malformed
        JSON, an object, a string, a number, ``null``, a list holding a non-string, empty text or SQL NULL): it never
        answers "none" then, because an erasure that cannot check must not go on as if nothing cited the episode (D10).
        One statement per call; ``_CITING_SQL`` skips only the canonical ``'[]'``.
        """
        if type(episode_ids) not in (list, tuple) or any(type(item) is not str for item in episode_ids):
            raise TypeError("AD-1341: entry_ids_citing takes a list or tuple of episode ids")
        if not self._db:
            raise RuntimeError("AD-1341 S3: the Ship's Archive is not open, so its citations cannot be read")
        wanted = {item for item in episode_ids if item}
        if not wanted:
            return ()
        cursor = await self._db.execute(_CITING_SQL)
        citing: list[int] = []
        for entry_id, cell in await cursor.fetchall():
            cited = json.loads(cell) if type(cell) is str else None  # SQL NULL, or a blob, is no citation list (D10)
            if type(cited) is not list or any(type(item) is not str for item in cited):
                raise ValueError(f"AD-1341 S3: Ship's Archive entry {entry_id}'s citation list cannot be read")
            if wanted.intersection(cited):
                citing.append(entry_id)
        return tuple(citing)

    async def entry_by_id(self, entry_id: int) -> ArchiveEntry | None:
```

### 7.2 `src/probos/knowledge/archive_promotion.py` (M1)

Pair 1 (the module docstring):

SEARCH:
```python
- Ship's Records carry no source-episode ids, so a records-sourced entry carries none (the lessons slice
  adds them).
"""
```
REPLACE:
```python
- Ship's Records carry no source-episode ids, so a records-sourced entry carries none (the lessons slice
  adds them).
- AD-1341 S3: a source the Captain vetoed is reported as vetoed and never archived. ``review_promotion`` is the
  Captain's review of the next run (``probos archive pending``): it reads, and records nothing.
"""
```

Pair 2 (imports):

SEARCH:
```python
from probos.knowledge.archive_store import (
    PROMOTABLE_CLASSIFICATIONS,
    ArchiveStore,
    PromotionOutcome,
    PromotionRecord,
    SourceKind,
)
```
REPLACE:
```python
from probos.knowledge.archive_store import (
    PROMOTABLE_CLASSIFICATIONS,
    ArchiveStore,
    PromotionOutcome,
    PromotionRecord,
    SourceKind,
    SourceState,
)
```

Pair 3 (the report's new field):

SEARCH:
```python
    created: tuple[str, ...]
    present: tuple[str, ...]
    erased: tuple[str, ...]
    withheld: tuple[str, ...]
```
REPLACE:
```python
    created: tuple[str, ...]
    present: tuple[str, ...]
    erased: tuple[str, ...]
    withheld: tuple[str, ...]
    vetoed: tuple[str, ...] = ()  # AD-1341 S3: sources the Captain vetoed; never archived
```

Pair 4 (the run reports a veto):

SEARCH:
```python
    created: list[str] = []
    present: list[str] = []
    erased: list[str] = []
    for record in plan.records:
        outcome = await archive.promote_entry(record)
        if outcome is PromotionOutcome.CREATED:
            created.append(record.source_ref)
        elif outcome is PromotionOutcome.ERASED:
            erased.append(record.source_ref)
        else:
            present.append(record.source_ref)
    logger.info(
        "AD-1341: Ship's Archive promotion for timeline %s: %d created, %d already archived, "
        "%d erased by the Captain, %d withheld",
        timeline_id, len(created), len(present), len(erased), len(plan.withheld),
    )
```
REPLACE:
```python
    created: list[str] = []
    present: list[str] = []
    erased: list[str] = []
    vetoed: list[str] = []
    for record in plan.records:
        outcome = await archive.promote_entry(record)
        if outcome is PromotionOutcome.CREATED:
            created.append(record.source_ref)
        elif outcome is PromotionOutcome.ERASED:
            erased.append(record.source_ref)
        elif outcome is PromotionOutcome.VETOED:  # AD-1341 S3: the Captain's veto, reported, never archived
            vetoed.append(record.source_ref)
        else:
            present.append(record.source_ref)
    logger.info(
        "AD-1341: Ship's Archive promotion for timeline %s: %d created, %d already archived, "
        "%d erased by the Captain, %d vetoed by the Captain, %d withheld",
        timeline_id, len(created), len(present), len(erased), len(vetoed), len(plan.withheld),
    )
```

Pair 5 (the report's field, and the review; the end of the file):

SEARCH:
```python
        created=tuple(created), present=tuple(present), erased=tuple(erased), withheld=plan.withheld,
    )
```
REPLACE:
```python
        created=tuple(created), present=tuple(present), erased=tuple(erased), withheld=plan.withheld,
        vetoed=tuple(vetoed),
    )


@dataclass(frozen=True)
class PendingSource:
    """AD-1341 S3: one source the next promotion would consider, and what promoting it now would do."""

    record: PromotionRecord
    state: SourceState


@dataclass(frozen=True)
class PromotionReview:
    """AD-1341 S3: the Captain's review of the next promotion, in the order Ship's Records lists the sources."""

    sources: tuple[PendingSource, ...]
    withheld: tuple[str, ...]


async def review_promotion(records: RecordsStore, archive: ArchiveStore, *, timeline_id: str) -> PromotionReview:
    """AD-1341 S3 (D3): every source that meets its criterion, with what promoting it now would do; and what is withheld.

    The queue is derived: the plan the next run would promote (``plan_promotion``), each source's state read from the
    archive (``ArchiveStore.source_state``). It reads Ship's Records and the archive and records nothing. A veto or
    erasure after the review decides the promotion (D6).
    """
    plan = await plan_promotion(records, timeline_id=timeline_id)
    sources = [PendingSource(record, await archive.source_state(record)) for record in plan.records]
    return PromotionReview(sources=tuple(sources), withheld=plan.withheld)
```

### 7.3 `docs/development/store-baseline.yaml` (M1: rule 11 pins the table set)

SEARCH:
```yaml
- module: probos.knowledge.archive_store
  tables:
  - archive
  - archive_erasures
  - generations
```
REPLACE:
```yaml
- module: probos.knowledge.archive_store
  tables:
  - archive
  - archive_erasures
  - archive_vetoes
  - generations
```

### 7.4 `tests/test_ad1341_s1_archive_store.py` (M1: A7 pins the public surface)

SEARCH:
```python
    assert public == {
        "initialize", "close", "promote_entry", "record_generation", "erase_entry", "entry_by_id",
        "search", "get_recent", "count",
    }
```
REPLACE:
```python
    # AD-1341 S3 (#1569): the Captain's veto (a write of no entry, Captain-only through ``probos archive veto``) and
    # two reads, the review's and the AD-754 erasure check's. There is still no update or delete of an entry.
    assert public == {
        "initialize", "close", "promote_entry", "record_generation", "erase_entry", "entry_by_id",
        "search", "get_recent", "count", "veto_source", "source_state", "entry_ids_citing",
    }
```

### 7.5 New file: `tests/test_ad1341_s3_veto_store.py` (M1)

```python
"""AD-1341 S3 M1 (#1569): the Captain's veto record, the review's read and the citation read of the Ship's Archive.

The real ``ArchiveStore`` through the startup's ``default_factory`` on a temporary file, read back with ``sqlite3``;
Ship's Records written by the store's own producers; the real promotion service. Every test states its premise first,
so "not archived" can never mean "was never eligible".
"""

from __future__ import annotations

import ast
import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.knowledge.archive_promotion import promote_ship_records, review_promotion
from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome, SourceKind, SourceState, VetoOutcome
from probos.storage.sqlite_factory import default_factory
from tests.test_ad1341_s1_archive_store import _plant_v0, _record, _rows, _store
from tests.test_ad1341_s1_reset_and_erase import (
    _CONVERGENCE,
    _NEXT_SHIP,
    _SHIP,
    _data_dir,
    _records,
    _write_records,
)

_SRC = Path(probos.__file__).resolve().parent
_SECOND = "reports/convergence/convergence-20261022-000001.md"
_REPORT = "reports/coolant-review.md"
_FINDING = "notebooks/Chapel/coolant-finding.md"
_PRIVATE = "notebooks/Chapel/private-coolant-c0ffee02.md"  # S1's private notebook: withheld (C1)
_REVISED = "## Convergence Report\n\nFour officers now trace the coolant drift."
_TABLES = ("archive", "archive_erasures", "archive_vetoes", "generations")
_VETO_COLUMNS = ["id", "timeline_id", "source_kind", "source_ref", "reason", "vetoed_at"]
_EXPECTED_STATE = {
    "new": SourceState(PromotionOutcome.CREATED, ()),
    "present": SourceState(PromotionOutcome.PRESENT, (1,)),
    "revised": SourceState(PromotionOutcome.CREATED, (1,)),
    "erased": SourceState(PromotionOutcome.ERASED, ()),
    "vetoed": SourceState(PromotionOutcome.VETOED, ()),
}


def _counts(path: Path) -> dict[str, int]:
    """Rows per table: what a read must leave as it found it."""
    return {table: _rows(path, f"SELECT COUNT(*) FROM {table}")[0][0] for table in _TABLES}


def _vetoes(path: Path) -> list[tuple[Any, ...]]:
    return _rows(path, "SELECT timeline_id, source_kind, source_ref, reason FROM archive_vetoes ORDER BY id")


def _naming(name: str) -> set[str]:
    """The ``src`` files that name ``name`` as an attribute or spell it as a string (S1's census rule)."""
    naming: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == name) or (
                isinstance(node, ast.Constant) and node.value == name
            ):
                naming.add(path.relative_to(_SRC).as_posix())
    return naming


async def _review_scene(data_dir: Path, archive: Any, path: Path) -> dict[str, str]:
    """Ship's Records and the archive in every state the review shows; returns each state's Ship's Records path."""
    await _write_records(data_dir)  # a convergence report, the Captain's log and a private notebook (withheld)
    writer = _records(data_dir)
    await writer.write_entry(
        author="system", path=_SECOND, content="## Convergence Report\n\nThe relief valves agree.",
        message="AD-551: Convergence report (valves)", classification="ship",
    )
    first = await promote_ship_records(writer, archive, timeline_id=_SHIP)
    assert len(first.created) == 3 and len(first.withheld) == 1  # premise: both reports and the Captain's log
    (log_ref,) = [ref for ref in first.created if ref.startswith("captains-log/")]
    (log_id,) = _rows(path, "SELECT id FROM archive WHERE source_ref = ?", (log_ref,))[0]
    assert await archive.erase_entry(log_id, "the Captain's own log stays aboard")
    await writer.write_entry(
        author="system", path=_CONVERGENCE, content=_REVISED,
        message="AD-551: Convergence report (coolant, revised)", classification="ship",
    )
    await writer.write_entry(
        author="Chapel", path=_REPORT, content="The coolant review, as published.", message="Coolant review",
        classification="ship", status="published",
    )
    assert await archive.veto_source(SourceKind.PUBLISHED_REPORT, _REPORT, "not canon yet") is VetoOutcome.RECORDED
    await writer.write_notebook(
        callsign="Chapel", topic_slug="coolant-finding", content="Claim: the coolant drift is thermal.",
        classification="ship", extra_frontmatter={"claim_id": "c0ffee03c0ffee03", "contest_state": "uncontested"},
    )
    return {"revised": _CONVERGENCE, "present": _SECOND, "erased": log_ref, "vetoed": _REPORT, "new": _FINDING}


# --- V1: the table -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["fresh", "s1-file"])
async def test_the_archive_has_a_content_free_veto_table_keyed_by_source(tmp_path: Path, shape: str) -> None:
    path = tmp_path / "archive.db"
    if shape == "s1-file":
        _plant_v0(path)
        earlier = _store(tmp_path)
        await earlier.initialize()
        await earlier.close()
        connection = sqlite3.connect(str(path))
        try:
            connection.execute("DROP TABLE archive_vetoes")  # the file as S1 left it: v1, with no veto table
            connection.commit()
        finally:
            connection.close()
        tables = {row[0] for row in _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "archive_vetoes" not in tables and "archive_erasures" in tables  # premise: an S1-era v1 file
    store = _store(tmp_path)
    await store.initialize()
    await store.close()

    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert [row[1] for row in _rows(path, "PRAGMA table_info(archive_vetoes)")] == _VETO_COLUMNS
    (sql,) = _rows(path, "SELECT sql FROM sqlite_master WHERE name = 'idx_archive_vetoes_source'")[0]
    assert sql.startswith("CREATE UNIQUE INDEX") and "(source_kind, source_ref)" in sql
    if shape == "s1-file":
        assert _rows(path, "SELECT title FROM archive ORDER BY id") == [("Legacy one",), ("Legacy two",)]


# --- V2 to V4: the veto ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("attempt", ["same-content", "revised-content", "next-timeline"])
async def test_a_vetoed_source_is_never_archived_with_any_content(tmp_path: Path, attempt: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = _record()
        assert _counts(path)["archive"] == 0  # premise: nothing archived yet
        outcome = await store.veto_source(
            record.source_kind, record.source_ref, "  not canon: one officer's reading  ", timeline_id=" timeline-one ",
        )
        assert outcome is VetoOutcome.RECORDED
        later = {
            "same-content": record,
            "revised-content": _record(content=_REVISED),
            "next-timeline": _record(timeline_id="timeline-two"),
        }[attempt]
        assert await store.promote_entry(later) is PromotionOutcome.VETOED
    finally:
        await store.close()

    assert _counts(path) == {"archive": 0, "archive_erasures": 0, "archive_vetoes": 1, "generations": 0}
    assert _vetoes(path) == [("timeline-one", "convergence_report", record.source_ref, "not canon: one officer's reading")]


@pytest.mark.parametrize(
    ("setup", "expected", "vetoes"),
    [("archived", VetoOutcome.ARCHIVED, 0), ("erased", VetoOutcome.ERASED, 0), ("again", VetoOutcome.ALREADY_VETOED, 1)],
    ids=["archived", "erased", "again"],
)
async def test_a_veto_that_would_change_nothing_writes_nothing(
    tmp_path: Path, setup: str, expected: VetoOutcome, vetoes: int,
) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = _record()
        if setup in ("archived", "erased"):
            assert await store.promote_entry(record) is PromotionOutcome.CREATED  # entry 1
        if setup == "erased":
            assert await store.erase_entry(1, "erased for the test")
        if setup == "again":
            assert await store.veto_source(record.source_kind, record.source_ref, "the first veto") is VetoOutcome.RECORDED

        assert await store.veto_source(record.source_kind, record.source_ref, "a second reason") is expected
    finally:
        await store.close()

    assert _counts(path)["archive_vetoes"] == vetoes
    assert _counts(path)["archive"] == (1 if setup == "archived" else 0)
    if setup == "again":
        assert _vetoes(path) == [("", "convergence_report", record.source_ref, "the first veto")]


@pytest.mark.parametrize(
    ("kind", "ref", "reason", "timeline"),
    [
        ("convergence_report", "reports/convergence/x.md", "why", ""),
        (SourceKind.PUBLISHED_REPORT, "   ", "why", ""),
        (SourceKind.PUBLISHED_REPORT, 7, "why", ""),
        (SourceKind.PUBLISHED_REPORT, "reports/x.md", "   ", ""),
        (SourceKind.PUBLISHED_REPORT, "reports/x.md", "x" * 501, ""),
        (SourceKind.PUBLISHED_REPORT, "reports/x.md", "why", 7),
    ],
    ids=["str-kind", "blank-ref", "int-ref", "blank-reason", "long-reason", "int-timeline"],
)
async def test_a_veto_needs_a_kind_a_source_and_a_reason(
    tmp_path: Path, kind: Any, ref: Any, reason: Any, timeline: Any,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        with pytest.raises(ValueError):
            await store.veto_source(kind, ref, reason, timeline_id=timeline)
    finally:
        await store.close()
    assert _counts(tmp_path / "archive.db")["archive_vetoes"] == 0


# --- V5, V5b: one rule for the review and the promotion -----------------------------------------------------------


@pytest.mark.parametrize("state", ["new", "present", "revised", "erased", "vetoed"])
async def test_the_review_reads_what_promote_entry_then_does(tmp_path: Path, state: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        original = _record()
        if state in ("present", "revised", "erased"):
            assert await store.promote_entry(original) is PromotionOutcome.CREATED  # entry 1
        if state == "erased":
            assert await store.erase_entry(1, "erased for the test")
        if state == "vetoed":
            assert await store.veto_source(original.source_kind, original.source_ref, "not canon") is VetoOutcome.RECORDED
        record = _record(content=_REVISED) if state == "revised" else original
        expected = _EXPECTED_STATE[state]
        before = _counts(path)

        preview = await store.source_state(record)

        assert _counts(path) == before  # a read: nothing recorded
        assert preview == expected
        assert await store.promote_entry(record) is expected.outcome
    finally:
        await store.close()


@pytest.mark.parametrize("between", ["veto", "erasure"])
async def test_a_veto_or_erasure_after_the_review_decides_the_promotion(tmp_path: Path, between: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        if between == "erasure":
            assert await store.promote_entry(_record()) is PromotionOutcome.CREATED  # entry 1, the earlier version
        record = _record(content=_REVISED)
        assert (await store.source_state(record)).outcome is PromotionOutcome.CREATED  # premise: it would be archived
        if between == "veto":
            assert await store.veto_source(record.source_kind, record.source_ref, "not canon") is VetoOutcome.RECORDED
        else:
            assert await store.erase_entry(1, "erased after the review")
        expected = PromotionOutcome.VETOED if between == "veto" else PromotionOutcome.ERASED

        assert await store.promote_entry(record) is expected
        assert (await store.source_state(record)).outcome is expected
    finally:
        await store.close()
    assert _rows(path, "SELECT COUNT(*) FROM archive WHERE content = ?", (_REVISED,)) == [(0,)]


# --- V6, V6b: the citation read -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (["ep-a"], ("one",)),
        (["ep-c", "ep-a"], ("one", "two")),
        (["ep-z"], ()),
        (["", "ep-b"], ("two",)),
        ([], ()),
        (("ep-b",), ("two",)),
    ],
    ids=["one", "two-in-id-order", "none", "blank-ignored", "empty", "tuple"],
)
async def test_the_entries_citing_an_episode_are_found_in_id_order(
    tmp_path: Path, asked: Any, expected: tuple[str, ...],
) -> None:
    path = tmp_path / "archive.db"
    _plant_v0(path)  # two AD-524 rows: no citations, never a match
    store = _store(tmp_path)
    await store.initialize()
    try:
        for name, cited in (("one", ("ep-a",)), ("two", ("ep-b", "ep-c")), ("none", ())):
            created = await store.promote_entry(_record(source_ref=f"reports/convergence/{name}.md", source_episode_ids=cited))
            assert created is PromotionOutcome.CREATED
        ids = {
            ref.rsplit("/", 1)[-1].removesuffix(".md"): entry_id
            for entry_id, ref in _rows(path, "SELECT id, source_ref FROM archive WHERE source_ref != ''")
        }
        before = _counts(path)

        found = await store.entry_ids_citing(asked)

        assert _counts(path) == before
    finally:
        await store.close()
    assert found == tuple(ids[name] for name in expected)


# A2 (finding M1-F1): every cell the read cannot interpret as a list of episode ids, each planted on its own.
_UNREADABLE_CELLS = {
    "corrupt-row": "{not json",
    "dict": '{"another": "ep-a"}',
    "dict-key": '{"ep-a": 1}',
    "string": '"ep-a"',
    "number-list": "[42]",
    "mixed-list": '["ep-a", 42]',
    "number": "42",
    "json-null": "null",
    "empty-text": "",
}


@pytest.mark.parametrize("fault", ["not-open", "a-string", *_UNREADABLE_CELLS, "sql-null"])
async def test_the_citation_read_never_answers_none_when_it_cannot_read(tmp_path: Path, fault: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    if fault == "not-open":
        with pytest.raises(RuntimeError):
            await store.entry_ids_citing(["ep-a"])
        return
    if fault == "sql-null":  # an AD-524 file whose citation column was added nullable before S1's migration ran
        _plant_v0(path)
        connection = sqlite3.connect(str(path))
        try:
            connection.execute("ALTER TABLE archive ADD COLUMN source_episode_ids TEXT")
            connection.commit()
        finally:
            connection.close()
    await store.initialize()
    try:
        if fault == "a-string":
            with pytest.raises(TypeError):
                await store.entry_ids_citing("ep-a")
            return
        if fault in _UNREADABLE_CELLS:
            connection = sqlite3.connect(str(path))
            try:
                connection.execute(
                    "INSERT INTO archive (timeline_id, category, title, content, archived_at, source_kind, source_ref, "
                    "source_episode_ids) VALUES ('t', 'c', 't', 'c', 0, 'convergence_report', 'r', ?)",
                    (_UNREADABLE_CELLS[fault],),
                )
                connection.commit()
            finally:
                connection.close()
        planted = [None, None] if fault == "sql-null" else [_UNREADABLE_CELLS[fault]]
        assert [row[0] for row in _rows(path, "SELECT source_episode_ids FROM archive ORDER BY id")] == planted

        with pytest.raises(ValueError):
            await store.entry_ids_citing(["ep-a"])
    finally:
        await store.close()


# --- V7: overlapping writes ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("first", ["veto", "promotion"])
async def test_a_veto_and_a_promotion_of_one_source_never_both_succeed(tmp_path: Path, first: str) -> None:
    """``gather`` starts its tasks in order, and the first takes the store's lock before the second runs, so each
    order runs deterministically and must end as that order requires (A2, finding M1-F3: K4)."""
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = _record()
        veto = store.veto_source(record.source_kind, record.source_ref, "an overlapping veto")
        promotion = store.promote_entry(record)
        if first == "veto":
            vetoed, promoted = await asyncio.gather(veto, promotion)
        else:
            promoted, vetoed = await asyncio.gather(promotion, veto)
    finally:
        await store.close()
    counts = _counts(path)
    assert (vetoed, promoted, counts["archive"], counts["archive_vetoes"]) == {
        "veto": (VetoOutcome.RECORDED, PromotionOutcome.VETOED, 0, 1),
        "promotion": (VetoOutcome.ARCHIVED, PromotionOutcome.CREATED, 1, 0),
    }[first]


class _PausedCommit:
    """A real connection whose next commit, once armed, waits until released and then fails (S1 D16 under test)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.armed = False
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def commit(self) -> None:
        if self.armed:
            self.armed = False
            self.waiting.set()
            await self.release.wait()
            raise sqlite3.OperationalError("an injected commit failure")
        await self._inner.commit()


class _PausedCommitFactory:
    """The startup's ``default_factory``, with its connection wrapped in ``_PausedCommit``."""

    connection: _PausedCommit

    async def connect(self, db_path: str, *, read_only: bool = False) -> _PausedCommit:
        self.connection = _PausedCommit(await default_factory.connect(db_path, read_only=read_only))
        return self.connection


def _paused_store(tmp_path: Path, factory: _PausedCommitFactory) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=factory)


@pytest.mark.parametrize("failing", ["veto-fails", "promotion-fails"])
async def test_a_write_whose_commit_fails_leaves_nothing_the_other_write_can_commit(
    tmp_path: Path, failing: str,
) -> None:
    """A2, finding M1-F2: the second write waits on the store's lock, and the first's failed commit is rolled back
    before it runs, so the second never commits, nor is decided by, what the failed write left uncommitted."""
    path = tmp_path / "archive.db"
    factory = _PausedCommitFactory()
    store = _paused_store(tmp_path, factory)
    await store.initialize()
    record = _record()

    def veto() -> Any:
        return store.veto_source(record.source_kind, record.source_ref, "the Captain's veto")

    tasks: list[asyncio.Task[Any]] = []
    try:
        factory.connection.armed = True
        tasks.append(asyncio.create_task(veto() if failing == "veto-fails" else store.promote_entry(record)))
        await asyncio.wait_for(factory.connection.waiting.wait(), 5)
        counts = _counts(path)
        assert counts["archive"] + counts["archive_vetoes"] == 0  # premise: the first write is not committed
        tasks.append(asyncio.create_task(store.promote_entry(record) if failing == "veto-fails" else veto()))
        done, _waiting = await asyncio.wait({tasks[1]}, timeout=0.2)
        assert not done  # the store's lock: the second write waits for the first to end
        factory.connection.release.set()
        with pytest.raises(sqlite3.OperationalError):
            await tasks[0]
        outcome = await asyncio.wait_for(tasks[1], 5)
    finally:
        factory.connection.release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()
    counts = _counts(path)
    if failing == "veto-fails":
        assert (outcome, counts["archive"], counts["archive_vetoes"]) == (PromotionOutcome.CREATED, 1, 0)
    else:
        assert (outcome, counts["archive"], counts["archive_vetoes"]) == (VetoOutcome.RECORDED, 0, 1)


# --- V8 to V10: the service --------------------------------------------------------------------------------------


async def test_the_promotion_reports_a_vetoed_source_and_archives_the_rest(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    await _write_records(data_dir)
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.veto_source(SourceKind.CONVERGENCE_REPORT, _CONVERGENCE, "not canon") is VetoOutcome.RECORDED
        report = await promote_ship_records(_records(data_dir), store, timeline_id=_SHIP)
    finally:
        await store.close()

    assert report.vetoed == (_CONVERGENCE,)
    assert len(report.created) == 1 and report.created[0].startswith("captains-log/")
    assert (report.present, report.erased, report.withheld) == ((), (), (_PRIVATE,))
    assert _rows(path, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(0,)]


async def test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        refs = await _review_scene(data_dir, store, path)
        before = _counts(path)

        review = await review_promotion(_records(data_dir), store, timeline_id=_NEXT_SHIP)

        after = _counts(path)
    finally:
        await store.close()
    ids = dict(_rows(path, "SELECT source_ref, id FROM archive"))
    states = {pending.record.source_ref: pending.state for pending in review.sources}
    assert states == {
        refs["revised"]: SourceState(PromotionOutcome.CREATED, (ids[refs["revised"]],)),
        refs["present"]: SourceState(PromotionOutcome.PRESENT, (ids[refs["present"]],)),
        refs["erased"]: SourceState(PromotionOutcome.ERASED, ()),
        refs["vetoed"]: SourceState(PromotionOutcome.VETOED, ()),
        refs["new"]: SourceState(PromotionOutcome.CREATED, ()),
    }
    assert {pending.record.timeline_id for pending in review.sources} == {_NEXT_SHIP}
    assert review.withheld == (_PRIVATE,)
    assert after == before


def test_only_the_review_reads_what_a_promotion_would_do() -> None:
    """``source_state`` is named in ``src`` by the review service alone, beside its definition."""
    assert _naming("source_state") == {"knowledge/archive_promotion.py"}
```

### 7.6 `src/probos/__main__.py` (M2)

Pair 1 (type-only imports):

SEARCH:
```python
    from probos.config import SystemConfig
    from probos.knowledge.archive_store import ArchiveStore
    from probos.knowledge.records_store import RecordsStore
```
REPLACE:
```python
    from probos.config import SystemConfig
    from probos.knowledge.archive_promotion import PromotionReview
    from probos.knowledge.archive_store import ArchiveStore, SourceState
    from probos.knowledge.records_store import RecordsStore
```

Pair 2 (the reset reports vetoed sources):

SEARCH:
```python
    return True, (
        f"Ship's Archive: {len(promoted.created)} promoted, {len(promoted.present)} already archived, "
        f"{len(promoted.erased)} erased by the Captain, {len(promoted.withheld)} withheld (timeline {timeline_id})."
    )
```
REPLACE:
```python
    return True, (
        f"Ship's Archive: {len(promoted.created)} promoted, {len(promoted.present)} already archived, "
        f"{len(promoted.erased)} erased by the Captain, {len(promoted.vetoed)} vetoed by the Captain, "
        f"{len(promoted.withheld)} withheld (timeline {timeline_id})."
    )
```

Pair 3 (the dry run points to the review):

SEARCH:
```python
    for path in plan.withheld:
        console.print(f"    - withheld: {escape(path)}")
    if plan.records and not timeline_id:
```
REPLACE:
```python
    for path in plan.withheld:
        console.print(f"    - withheld: {escape(path)}")
    if plan.records:  # AD-1341 S3: the Captain reviews, and may veto, before the reset promotes
        console.print(
            "  [dim]probos archive pending shows what each would do now; "
            "probos archive veto SOURCE_REF --reason TEXT keeps one out of the Ship's Archive.[/dim]"
        )
    if plan.records and not timeline_id:
```

Pair 4 (the dispatch):

SEARCH:
```python
    if getattr(args, "archive_cmd", None) != "erase":
        print("usage: probos archive erase ENTRY_ID --reason TEXT [--yes] [--config PATH]")
        return 2
```
REPLACE:
```python
    command = getattr(args, "archive_cmd", None)
    if command == "pending":  # AD-1341 S3: the Captain's review before canon
        return _cmd_archive_pending(args)
    if command == "veto":  # AD-1341 S3: the Captain's veto
        return _cmd_archive_veto(args)
    if command != "erase":
        print(
            "usage: probos archive erase ENTRY_ID --reason TEXT | pending | veto SOURCE_REF --reason TEXT "
            "[--yes] [--config PATH] [--data-dir DIR]"
        )
        return 2
```

Pair 5 (the two commands, after the erasure):

SEARCH:
```python
    print(
        f"Erased Ship's Archive entry {entry_id}. A marker records the erasure: if its source is still in Ship's "
        "Records, it will not be promoted again."
    )
    return 0


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
```
REPLACE:
```python
    print(
        f"Erased Ship's Archive entry {entry_id}. A marker records the erasure: if its source is still in Ship's "
        "Records, it will not be promoted again."
    )
    return 0


def _cmd_archive_pending(args: argparse.Namespace) -> int:
    """``probos archive pending`` (AD-1341 S3): the Captain's review of what the next promotion would archive.

    Every Ship's Records document that meets its source's criterion, with what promoting it now would do: archive it
    (new, or a revision of the entries named), nothing (already archived), or never (vetoed or erased by the
    Captain); then what is withheld (C1). It reads Ship's Records and the Ship's Archive and records nothing; opening
    the archive brings its schema up to date, as ``erase`` does. 0 shown; 1 a read failed; 2 the archive disabled.
    Plain ``print``: a path is shown as text, never as markup.
    """
    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:  # AD-1341 S3: a disabled archive is never opened, so pending creates no file
        print("The Ship's Archive is disabled (archive.enabled): nothing is promoted, so there is nothing to review.")
        return 2
    data_dir = Path(getattr(args, "data_dir", None) or _default_data_dir())
    timeline_id = _read_instance_id(data_dir) or _UNATTRIBUTED_TIMELINE
    try:
        review = asyncio.run(_review_pending_promotion(config, data_dir, timeline_id))
    except Exception as exc:  # nothing is recorded either way; the Captain sees why
        print(f"The review could not be read: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"Ship's Archive review for timeline {timeline_id}: {len(review.sources)} eligible, "
        f"{len(review.withheld)} withheld"
    )
    for pending in review.sources:
        print(f"  {_pending_label(pending.state)}: {pending.record.source_ref}")
    for path in review.withheld:
        print(f"  - withheld: {path}")
    if review.sources:
        print(
            "Veto a source: probos archive veto SOURCE_REF --reason TEXT. "
            "Erase an archived entry: probos archive erase ENTRY_ID --reason TEXT."
        )
    return 0


async def _review_pending_promotion(config: SystemConfig, data_dir: Path, timeline_id: str) -> PromotionReview:
    """The review over this vessel's Ship's Records and the configured archive; the archive is closed on every exit."""
    from probos.knowledge.archive_promotion import review_promotion

    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        return await review_promotion(_reset_records_store(config, data_dir), archive, timeline_id=timeline_id)
    finally:
        await archive.close()


def _pending_label(state: SourceState) -> str:
    """What promoting a source now would do, as ``probos archive pending`` shows it (AD-1341 S3)."""
    from probos.knowledge.archive_store import PromotionOutcome

    entries = ", ".join(str(entry_id) for entry_id in state.entry_ids)
    if state.outcome is PromotionOutcome.ERASED:
        return "x erased by the Captain"
    if state.outcome is PromotionOutcome.VETOED:
        return "x vetoed by the Captain"
    if state.outcome is PromotionOutcome.PRESENT:
        return f"= already archived (entry {entries})"
    return f"+ would be promoted (a revision of entry {entries})" if entries else "+ would be promoted"


def _cmd_archive_veto(args: argparse.Namespace) -> int:
    """``probos archive veto SOURCE_REF --reason TEXT`` (AD-1341 S3): the Captain vetoes a source before it is archived.

    The source must be one the next promotion would archive (``probos archive pending`` lists them). The veto keeps the
    source's kind and path, the reason, the timeline and the time, never its title or content, and no later promotion
    archives that source, with any content. A source already archived is refused: erase its entry instead. 0 vetoed,
    already vetoed, already erased, or declined; 1 not a pending source, already archived, or the veto failed; 2 the
    archive disabled, or a blank source or a bad reason. Plain ``print``.
    """
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): nothing is promoted, so there is nothing to veto.")
        return 2
    source_ref, reason = args.source_ref.strip(), args.reason
    if not source_ref:
        print("A source is its Ship's Records path, as probos archive pending lists it.")
        return 2
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        print(f"--reason needs 1 to {ARCHIVE_REASON_MAX_CHARS} characters. Do not restate the source's content.")
        return 2
    data_dir = Path(getattr(args, "data_dir", None) or _default_data_dir())
    try:
        return asyncio.run(_veto_pending_source(config, data_dir, source_ref, reason, bool(getattr(args, "yes", False))))
    except Exception as exc:  # one statement, so nothing is half-recorded; the Captain sees why
        print(f"The veto failed: {type(exc).__name__}: {exc}")
        return 1


async def _veto_pending_source(
    config: SystemConfig, data_dir: Path, source_ref: str, reason: str, confirmed: bool,
) -> int:
    """Find the pending source, show it, ask unless ``--yes``, then record the veto. The archive is closed on every exit."""
    from probos.knowledge.archive_promotion import plan_promotion
    from probos.knowledge.archive_store import VetoOutcome

    timeline_id = _read_instance_id(data_dir)
    plan = await plan_promotion(
        _reset_records_store(config, data_dir), timeline_id=timeline_id or _UNATTRIBUTED_TIMELINE,
    )
    record = next((item for item in plan.records if item.source_ref == source_ref), None)
    if record is None:
        print(
            f"{source_ref} is not a source the next promotion would archive (not in Ship's Records, not eligible, "
            "or withheld). probos archive pending lists the sources."
        )
        return 1
    print(f"Ship's Records source {record.source_ref}: {record.title}")
    print(f"  kind: {record.source_kind.value}")
    if not confirmed and input("  Veto its promotion into the Ship's Archive? [y/N]: ").strip().lower() != "y":
        print("Aborted. Nothing was vetoed.")
        return 0
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        outcome = await archive.veto_source(record.source_kind, record.source_ref, reason, timeline_id=timeline_id)
    finally:
        await archive.close()
    if outcome is VetoOutcome.ARCHIVED:
        print(
            "An entry from this source is already in the Ship's Archive, and a veto does not remove it. "
            "probos archive pending shows its id; erase it with probos archive erase ENTRY_ID --reason TEXT."
        )
        return 1
    if outcome is VetoOutcome.ERASED:
        print("The Captain already erased this source's entry, so it is never promoted again. Nothing changed.")
        return 0
    if outcome is VetoOutcome.ALREADY_VETOED:
        print("This source is already vetoed. Nothing changed.")
        return 0
    print("Vetoed: this source is never promoted into the Ship's Archive. The veto and its reason are recorded.")
    return 0


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
```

Pair 6 (the parser's help line):

SEARCH:
```python
    # --- probos archive (AD-1341 S1): the Captain's erasure ---
    archive_parser = subparsers.add_parser("archive", help="The Ship's Archive: the Captain's erasure (AD-1341)")
```
REPLACE:
```python
    # --- probos archive (AD-1341 S1, S3): the Captain's erasure, review and veto ---
    archive_parser = subparsers.add_parser(
        "archive", help="The Ship's Archive: the Captain's review, veto and erasure (AD-1341)",
    )
```

Pair 7 (the two sub-commands):

SEARCH:
```python
    archive_erase.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_erase.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")

    args = parser.parse_args()
```
REPLACE:
```python
    archive_erase.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_erase.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    # AD-1341 S3: SUPPRESS keeps a root --config or --data-dir given before the command (S1 D19).
    archive_pending = archive_sub.add_parser(
        "pending", help="List what the next promotion would archive, and what the Captain vetoed or erased",
    )
    archive_pending.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    archive_pending.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
    archive_veto = archive_sub.add_parser(
        "veto", help="Veto one Ship's Records source: it is never promoted into the Ship's Archive",
    )
    archive_veto.add_argument("source_ref", type=str, help="The source's Ship's Records path, as pending lists it")
    archive_veto.add_argument(
        "--reason", type=str, required=True,
        help="Why, in 1-500 characters; it is recorded. Do not restate the source's content.",
    )
    archive_veto.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_veto.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    archive_veto.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")

    args = parser.parse_args()
```

### 7.7 New file: `tests/test_ad1341_s3_review_cli.py` (M2)

```python
"""AD-1341 S3 M2 (#1569): ``probos archive pending`` and ``probos archive veto``, the Captain's review before canon.

The real ``_cmd_archive``, ``_cmd_reset`` and ``main`` on a temporary data directory, with S1's real configuration,
Ship's Records producers, ``ArchiveStore`` and ``OracleService``. The config loader is the one stand-in, as in S1's
tests (``main``'s dispatch test also replaces the command it dispatches to). The tests are synchronous, because each
command runs its own event loop, as the CLI does.
"""

from __future__ import annotations

import asyncio
from argparse import Namespace as _Namespace
from pathlib import Path
from typing import Any

import pytest

from probos import __main__ as cli
from tests.test_ad1341_s1_reset_and_erase import (
    _CONVERGENCE,
    _NEXT_SHIP,
    _SHIP,
    _archive_store,
    _config,
    _data_dir,
    _erase,
    _oracle_query,
    _records,
    _reset,
    _rows,
    _write_records,
)
from tests.test_ad1341_s3_veto_store import _PRIVATE, _REVISED, _counts, _naming, _review_scene


def _archive(monkeypatch: pytest.MonkeyPatch, config: Any, data_dir: Path, command: str, **values: Any) -> Any:
    """The real ``_cmd_archive`` with the loader returning ``config``; returns what it returns."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(_Namespace(archive_cmd=command, config=None, data_dir=data_dir, **values))


def _veto(
    monkeypatch: pytest.MonkeyPatch, config: Any, data_dir: Path, source_ref: str, reason: str = "not canon",
    *, yes: bool = True,
) -> Any:
    return _archive(monkeypatch, config, data_dir, "veto", source_ref=source_ref, reason=reason, yes=yes)


def _vetoes_on_disk(archive: Path) -> int:
    """Veto rows, without creating the file when the command never opened it."""
    if not archive.exists():
        return 0
    return _rows(archive, "SELECT COUNT(*) FROM archive_vetoes")[0][0]


# --- C1: the review ------------------------------------------------------------------------------------------------


def test_pending_shows_what_the_next_promotion_would_do_with_each_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    archive = tmp_path / "archive.db"

    async def _scene() -> dict[str, str]:
        store = _archive_store(tmp_path)
        await store.initialize()
        try:
            return await _review_scene(data_dir, store, archive)
        finally:
            await store.close()

    refs = asyncio.run(_scene())
    ids = dict(_rows(archive, "SELECT source_ref, id FROM archive"))
    before = _counts(archive)

    assert _archive(monkeypatch, _config(tmp_path), data_dir, "pending") == 0

    out = capsys.readouterr().out
    assert f"Ship's Archive review for timeline {_SHIP}: 5 eligible, 1 withheld" in out
    assert f"  + would be promoted (a revision of entry {ids[refs['revised']]}): {refs['revised']}" in out
    assert f"  = already archived (entry {ids[refs['present']]}): {refs['present']}" in out
    assert f"  x erased by the Captain: {refs['erased']}" in out
    assert f"  x vetoed by the Captain: {refs['vetoed']}" in out
    assert f"  + would be promoted: {refs['new']}" in out
    assert f"  - withheld: {_PRIVATE}" in out
    assert _counts(archive) == before


def test_pending_refuses_a_disabled_archive_and_creates_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2, finding M2-F2: the disabled archive's own refusal, which the M1 base's usage line does not print."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))  # premise: sources a review would list, were the archive enabled

    assert _archive(monkeypatch, _config(tmp_path, archive_enabled=False), data_dir, "pending") == 2

    assert "nothing is promoted, so there is nothing to review." in capsys.readouterr().out
    assert not (tmp_path / "archive.db").exists()


# --- C2: the real seam -------------------------------------------------------------------------------------------


def test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    archive = tmp_path / "archive.db"

    assert _archive(monkeypatch, config, data_dir, "pending") == 0
    assert f"  + would be promoted: {_CONVERGENCE}" in capsys.readouterr().out  # premise: it is pending

    assert _veto(monkeypatch, config, data_dir, _CONVERGENCE, "  not canon: one officer's reading  ") == 0
    assert "never promoted" in capsys.readouterr().out
    assert _rows(archive, "SELECT timeline_id, source_kind, source_ref, reason FROM archive_vetoes") == [
        (_SHIP, "convergence_report", _CONVERGENCE, "not canon: one officer's reading"),
    ]

    assert _reset(monkeypatch, config, data_dir) == 0
    assert "1 vetoed by the Captain" in capsys.readouterr().out
    assert _rows(archive, "SELECT source_kind FROM archive") == [("captains_log",)]

    # The next crew revises the report; its reset does not archive it either.
    (data_dir / "ontology" / "instance_id").write_text(_NEXT_SHIP, encoding="utf-8")
    asyncio.run(_records(data_dir).write_entry(
        author="system", path=_CONVERGENCE, content=_REVISED, message="AD-551: Convergence report (revised)",
        classification="ship",
    ))
    assert _reset(monkeypatch, config, data_dir) == 0
    assert "1 vetoed by the Captain" in capsys.readouterr().out
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(0,)]
    assert _rows(
        archive,
        "SELECT timeline_id, created_count, present_count, erased_count, withheld_count FROM generations ORDER BY id",
    ) == [(_SHIP, 1, 0, 0, 1), (_NEXT_SHIP, 0, 1, 0, 1)]

    results = asyncio.run(_oracle_query(tmp_path, "coolant drift"))
    assert results  # premise: the Captain's log is there to be read
    assert not any("officers" in result.content for result in results)  # the vetoed report never reached a crew

    assert _archive(monkeypatch, config, data_dir, "pending") == 0
    assert f"  x vetoed by the Captain: {_CONVERGENCE}" in capsys.readouterr().out


# --- C3: what a veto refuses ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "code", "vetoes"),
    [
        ("not-eligible", 1, 0),
        ("withheld", 1, 0),
        ("archived", 1, 0),
        ("erased", 0, 0),
        ("again", 0, 1),
        ("blank-reason", 2, 0),
        ("declined", 0, 0),
        ("disabled", 2, 0),
    ],
    ids=["not-eligible", "withheld", "archived", "erased", "again", "blank-reason", "declined", "disabled"],
)
def test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str, code: int,
    vetoes: int,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path, archive_enabled=case != "disabled")
    archive = tmp_path / "archive.db"
    ref, reason, yes = _CONVERGENCE, "not canon", True
    if case in ("archived", "erased"):
        assert _reset(monkeypatch, config, data_dir) == 0  # archives the report
    if case == "erased":
        (entry_id,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]
        assert _erase(monkeypatch, config, entry_id, "superseded") == 0
    if case == "again":
        assert _veto(monkeypatch, config, data_dir, _CONVERGENCE, "the first veto") == 0
    if case == "not-eligible":
        ref = "reports/no-such-report.md"
    if case == "withheld":
        ref = _PRIVATE
    if case == "blank-reason":
        reason = "   "
    if case == "declined":
        yes = False
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert _veto(monkeypatch, config, data_dir, ref, reason, yes=yes) == code

    out = capsys.readouterr().out
    if case == "blank-reason":  # the veto's own refusal, never the usage line the M1 base prints (A2, M2-F1)
        assert "Do not restate the source's content." in out
    if case == "disabled":
        assert "nothing is promoted, so there is nothing to veto." in out
    assert _vetoes_on_disk(archive) == vetoes
    if case == "disabled":
        assert not archive.exists()


# --- C4, C5: the parser and the dry run --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "attribute", "value"),
    [
        (["archive", "pending"], "archive_cmd", "pending"),
        (["--data-dir", "elsewhere", "archive", "pending"], "data_dir", Path("elsewhere")),
        (["archive", "veto", _CONVERGENCE, "--reason", "not canon", "--yes"], "source_ref", _CONVERGENCE),
        (["--config", "named.yaml", "archive", "veto", _CONVERGENCE, "--reason", "r"], "config", Path("named.yaml")),
        (["archive", "veto", _CONVERGENCE, "--reason", "r", "--data-dir", "elsewhere"], "data_dir", Path("elsewhere")),
    ],
    ids=["pending", "pending-root-data-dir", "veto", "veto-root-config", "veto-own-data-dir"],
)
def test_main_dispatches_pending_and_veto_with_the_captains_options(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], attribute: str, value: Any,
) -> None:
    seen: list[_Namespace] = []

    def _command(args: _Namespace) -> int:
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


def test_the_dry_run_points_the_captain_to_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "2 to promote, 1 withheld" in out  # S1's plan line, unchanged
    assert "probos archive pending" in out and "probos archive veto" in out
    assert not (tmp_path / "archive.db").exists()


def test_only_the_cli_vetoes_a_source() -> None:
    """``veto_source`` is named in ``src`` by ``__main__.py`` alone: no agent or service vetoes or un-vetoes."""
    assert _naming("veto_source") == {"__main__.py"}
```

### 7.8 `src/probos/knowledge/erasure.py` (M3)

Pair 1 (import):

SEARCH:
```python
from probos.security.audit_log import AuditLog
from probos.types import EvictionDisposition
```
REPLACE:
```python
from probos.knowledge.archive_store import ArchiveStore
from probos.security.audit_log import AuditLog
from probos.types import EvictionDisposition
```

Pair 2 (the refusal and its check, after `ErasureCascadeIncomplete`):

SEARCH:
```python
        self.result = result
        self.failures = failures
        self.enumeration_error = enumeration_error
```
REPLACE:
```python
        self.result = result
        self.failures = failures
        self.enumeration_error = enumeration_error


class ArchiveCitationsBlockErasure(Exception):
    """AD-1341 S3 (D8): Ship's Archive entries cite episodes this erasure would erase, so nothing was erased.

    ``entry_ids`` are those entries. The Captain erases each with ``probos archive erase ENTRY_ID --reason TEXT`` and
    retries. The archive is append-only for agents and services, so this path never erases an entry itself; and
    erasing the episodes first would leave entries citing them that no later scan could find. The message carries the
    count only.
    """

    def __init__(self, entry_ids: tuple[int, ...]) -> None:
        super().__init__(f"archive_entries_cite_erased_episodes:count={len(entry_ids)}")
        self.entry_ids = entry_ids


async def _refuse_while_the_archive_cites(archive: ArchiveStore | None, episode_ids: list[str]) -> None:
    """AD-1341 S3 (D8, D10): raise ``ArchiveCitationsBlockErasure`` before anything is erased if an entry cites one.

    No open archive (disabled, failed at boot, or closed at shutdown): nothing to check, as before S3. A failed read
    propagates, so the erasure stops with nothing erased. A module function, so ``ErasureManager`` stays within its
    15-method SRP trigger.
    """
    if archive is None or not episode_ids:
        return
    citing = await archive.entry_ids_citing(episode_ids)
    if citing:
        raise ArchiveCitationsBlockErasure(citing)
```

Pair 3 (the manager takes the archive):

SEARCH:
```python
        audit_log: AuditLog | None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._attachment_store = attachment_store
        self._audit_log = audit_log
```
REPLACE:
```python
        audit_log: AuditLog | None,
        *,
        archive_store: ArchiveStore | None = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._attachment_store = attachment_store
        self._audit_log = audit_log
        # AD-1341 S3: the open Ship's Archive, read only to refuse an erasure while an entry cites its episodes
        self._archive_store = archive_store
```

Pair 4 (one episode: checked before its attachments):

SEARCH:
```python
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        unlinked = await self._delete_attachments(attachment_ids)
```
REPLACE:
```python
        await _refuse_while_the_archive_cites(self._archive_store, [episode_id])  # AD-1341 S3: before anything is erased
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        unlinked = await self._delete_attachments(attachment_ids)
```

Pair 5 (a resource: checked after the scan):

SEARCH:
```python
    async def forget_resource(self, resource_path: str) -> ErasureResult:
        """Delete all episodes that mention a resource path.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase.
        """
        needle = resource_path.lower()

        def mentions_resource(episode: Any) -> bool:
            serialized = json.dumps(self._episode_to_dict(episode), sort_keys=True, default=str).lower()
            return needle in serialized

        matching_ids, enumeration_error = await self._matching_ids(mentions_resource)
        return await self._forget_all(matching_ids, enumeration_error)
```
REPLACE:
```python
    async def forget_resource(self, resource_path: str) -> ErasureResult:
        """Delete all episodes that mention a resource path.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase. AD-1341 S3: erases
        nothing, raising ``ArchiveCitationsBlockErasure``, while a Ship's Archive entry cites a match.
        """
        needle = resource_path.lower()

        def mentions_resource(episode: Any) -> bool:
            serialized = json.dumps(self._episode_to_dict(episode), sort_keys=True, default=str).lower()
            return needle in serialized

        matching_ids, enumeration_error = await self._matching_ids(mentions_resource)
        await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: a resource's matches
        return await self._forget_all(matching_ids, enumeration_error)
```

Pair 6 (an agent: checked after the scan):

SEARCH:
```python
    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
        """Delete all episodes involving a specific agent.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase.
        """

        def involves_agent(episode: Any) -> bool:
            return agent_id in list(getattr(episode, "agent_ids", []) or [])

        matching_ids, enumeration_error = await self._matching_ids(involves_agent)
        return await self._forget_all(matching_ids, enumeration_error)
```
REPLACE:
```python
    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
        """Delete all episodes involving a specific agent.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase. AD-1341 S3: erases
        nothing, raising ``ArchiveCitationsBlockErasure``, while a Ship's Archive entry cites a match; an entry the
        agent authored that cites none of them does not block it (D9).
        """

        def involves_agent(episode: Any) -> bool:
            return agent_id in list(getattr(episode, "agent_ids", []) or [])

        matching_ids, enumeration_error = await self._matching_ids(involves_agent)
        await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: an agent's matches
        return await self._forget_all(matching_ids, enumeration_error)
```

### 7.9 `src/probos/routers/security.py` (M3)

Pair 1 (imports):

SEARCH:
```python
from probos.credential_store import crew_scope_token
from probos.knowledge.erasure import ErasureManager
from probos.routers.auth import require_crew_scope
```
REPLACE:
```python
from probos.credential_store import crew_scope_token
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager
from probos.routers.auth import require_crew_scope
```

Pair 2 (the docstring and the archive):

SEARCH:
```python
    """User-directed erasure for episode, resource, or agent memory."""
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
```
REPLACE:
```python
    """User-directed erasure for episode, resource, or agent memory.

    AD-1341 S3: while a Ship's Archive entry cites an episode this request would erase, nothing is erased and the
    answer is 409 with the entries' ids. The archive is append-only for agents and services, so this route never
    erases an entry: the Captain erases each with ``probos archive erase ENTRY_ID --reason TEXT``, then retries.
    """
    archive = getattr(runtime, "archive_store", None)  # AD-1341 S3: consulted only when it is a real store
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
```

Pair 3 (the archive reaches the manager):

SEARCH:
```python
        attachment_store=getattr(runtime, "attachment_store", None),
        audit_log=_get_audit_log(runtime),
    )
```
REPLACE:
```python
        attachment_store=getattr(runtime, "attachment_store", None),
        audit_log=_get_audit_log(runtime),
        archive_store=archive if isinstance(archive, ArchiveStore) else None,  # AD-1341 S3: a real store, or none
    )
```

Pair 4 (the refusal's answer):

SEARCH:
```python
    if request.episode_id:
        result = await manager.forget_episode(request.episode_id, reason=request.reason)
    elif request.resource_path:
        result = await manager.forget_resource(request.resource_path)
    elif request.agent_id:
        result = await manager.forget_agent_memory(request.agent_id)
    else:
        return JSONResponse(
            {"error": "one erasure target is required"},
            status_code=400,
        )
```
REPLACE:
```python
    try:
        if request.episode_id:
            result = await manager.forget_episode(request.episode_id, reason=request.reason)
        elif request.resource_path:
            result = await manager.forget_resource(request.resource_path)
        elif request.agent_id:
            result = await manager.forget_agent_memory(request.agent_id)
        else:
            return JSONResponse(
                {"error": "one erasure target is required"},
                status_code=400,
            )
    except ArchiveCitationsBlockErasure as exc:  # AD-1341 S3 (D8): nothing was erased
        logger.warning(
            "AD-1341 S3: an AD-754 erasure was refused: %d Ship's Archive entr(ies) cite its episodes",
            len(exc.entry_ids),
        )
        return JSONResponse(
            {
                "error": "archive_entries_cite_erased_episodes",
                "archive_entry_ids": list(exc.entry_ids),
                "next": "probos archive erase ENTRY_ID --reason TEXT for each, then retry",
            },
            status_code=409,
        )
```

### 7.10 `src/probos/runtime.py` (M3; S2 edits only the BF-679 block)

SEARCH:
```python
    @property
    def records_store(self):
        """Ship's Records service (AD-434)."""
        return self._records_store
```
REPLACE:
```python
    @property
    def records_store(self):
        """Ship's Records service (AD-434)."""
        return self._records_store

    @property
    def archive_store(self) -> Any:
        """AD-1341 S3: the Ship's Archive store (AD-524), or None when it is disabled, failed to start or is closed.

        Read by the AD-754 route (``routers/security.py``) so an erasure refuses while an archive entry cites an
        episode it would erase. Read-only; shutdown clears ``_archive_store`` after closing it.
        """
        return self._archive_store
```

### 7.11 New file: `tests/test_ad1341_s3_erasure_cascade.py` (M3)

```python
"""AD-1341 S3 M3 (#1569): an AD-754 erasure erases nothing while a Ship's Archive entry cites its episodes.

A real ``EpisodicMemory`` (ChromaDB, FTS5 and every sidecar, from ``test_ad1340_s1_eviction``), the real
``ErasureManager``, the real ``ArchiveStore``, the real app's ``POST /api/security/forget`` (S2a's client) and the
Captain's real ``probos archive erase``. Entries citing episodes are written with ``promote_entry`` directly: no
production source cites an episode until S4, so the test is the producer.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import dataclasses
import hashlib
import inspect
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureCascadeIncomplete, ErasureManager
from probos.runtime import ProbOSRuntime
from probos.security.audit_log import AuditLog
from probos.storage.sqlite_factory import default_factory
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_ad1341_s1_archive_store import _record, _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _config, _erase
from tests.test_ad1341_s3_veto_store import _SRC, _naming

_FORGET = "/api/security/forget"
_CITED, _OTHER = "ep-000", "ep-001"
_RESOURCE = "/srv/reactor.log"
_TARGETS: dict[str, dict[str, str]] = {
    "episode": {"episode_id": _CITED},
    "agent": {"agent_id": "agent-a"},
    "resource": {"resource_path": _RESOURCE},
}
_MATCHED = {"episode": [_CITED], "agent": [_CITED, _OTHER], "resource": [_CITED]}  # of the two stored episodes
_BODY = b"the coolant readings, photographed"
_SHA = hashlib.sha256(_BODY).hexdigest()  # the cited episode's one attachment (E9)


class _CitedMidway(ArchiveStore):
    """The real store; just after its first citation read, a promotion citing ``_CITED`` lands (D10, E8, E9).

    With ``unreadable`` set to the archive's path, the landed entry's citation cell is then rewritten as a JSON
    object, which the read cannot interpret (A2, finding M1-F1 read late: E8 ``[unreadable-cell]``).
    """

    landed = False
    unreadable: Path | None = None

    async def entry_ids_citing(self, episode_ids: list[str] | tuple[str, ...]) -> tuple[int, ...]:
        found = await super().entry_ids_citing(episode_ids)
        if not self.landed:
            self.landed = True
            late = _record(source_ref="reports/convergence/midway.md", source_episode_ids=(_CITED,))
            assert await self.promote_entry(late) is PromotionOutcome.CREATED
            if self.unreadable is not None:
                connection = sqlite3.connect(str(self.unreadable))
                try:
                    connection.execute(
                        "UPDATE archive SET source_episode_ids = ? WHERE source_ref = ?",
                        ('{"another": "ep-000"}', "reports/convergence/midway.md"),
                    )
                    connection.commit()
                finally:
                    connection.close()
        return found


def _midway(tmp_path: Path, *, unreadable: bool = False) -> _CitedMidway:
    store = _CitedMidway(str(tmp_path / "archive.db"), connection_factory=default_factory)
    store.unreadable = tmp_path / "archive.db" if unreadable else None
    return store


def _episodes() -> list[Any]:
    """Two episodes of agent-a; only the first names the resource."""
    cited = dataclasses.replace(_episode(0), user_input=f"alpha section filed the coolant readings under {_RESOURCE}")
    return [cited, _episode(1)]


def _with_archive(memory: Any, archive: Any, attachments: Any = None, audit: Any = None) -> ErasureManager:
    options = {"archive_store": archive}  # S3's keyword, passed as a mapping
    return ErasureManager(memory, attachments, audit, **options)


@contextlib.asynccontextmanager
async def _traced(
    tmp_path: Path, archive: ArchiveStore,
) -> AsyncIterator[tuple[Any, ErasureManager, FilesystemAttachmentStore, AuditLog]]:
    """Every trace an erasure removes, real (A2, finding M3-F1): the two episodes, the cited one's attachment in a
    real ``FilesystemAttachmentStore``, and one row per episode in a real assistant ``AuditLog``."""
    async with _memory(tmp_path / "vessel", "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        audit = AuditLog(str(tmp_path / "assistant_audit.db"))
        try:
            await attachments.write(_SHA, _BODY, "text/plain")
            cited, other = _episodes()
            cited = dataclasses.replace(
                cited, outcomes=[{"intent": "report", "success": True, "attachment_refs": [_SHA]}],
            )
            for episode in (cited, other):
                assert await rig.em.store(episode) is EpisodeStoreOutcome.STORED
                await audit.log_intent("report", episode.id, "agent-a", True)
            premise = ([_CITED, _OTHER], True, [_CITED, _OTHER])
            assert await _traces(rig.em, attachments, audit) == premise  # both episodes, the attachment, two rows
            yield rig, _with_archive(rig.em, archive, attachments, audit), attachments, audit
        finally:
            attachments.close()


async def _traces(
    em: Any, attachments: FilesystemAttachmentStore, audit: AuditLog,
) -> tuple[list[str], bool, list[str]]:
    """The live episodes, whether the cited episode's attachment exists, and the audit rows' resources, sorted."""
    return _live(em), await attachments.exists(_SHA), sorted(entry.resource for entry in await audit.query())


async def _forget(manager: ErasureManager, target: str) -> Any:
    if target == "episode":
        return await manager.forget_episode(_CITED)
    if target == "agent":
        return await manager.forget_agent_memory("agent-a")
    return await manager.forget_resource(_RESOURCE)


async def _stored(em: Any) -> None:
    for episode in _episodes():
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
    assert _live(em) == [_CITED, _OTHER]  # premise: both are live


def _live(em: Any) -> list[str]:
    return sorted(_raw(em, [_CITED, _OTHER])["ids"])


async def _archive_with(tmp_path: Path, cited: tuple[str, ...]) -> tuple[ArchiveStore, int, int]:
    """An open archive: one entry citing ``cited``, and one the agent authored that cites nothing (D9)."""
    store = _store(tmp_path)
    await store.initialize()
    assert await store.promote_entry(_record(source_episode_ids=cited)) is PromotionOutcome.CREATED
    authored = _record(source_ref="reports/convergence/authored.md", author_did="agent-a", author_callsign="agent-a")
    assert await store.promote_entry(authored) is PromotionOutcome.CREATED
    citing, unrelated = (row[0] for row in _rows(tmp_path / "archive.db", "SELECT id FROM archive ORDER BY id"))
    return store, citing, unrelated


def _archive_counts(tmp_path: Path) -> tuple[int, int]:
    archive = tmp_path / "archive.db"
    return (
        _rows(archive, "SELECT COUNT(*) FROM archive")[0][0],
        _rows(archive, "SELECT COUNT(*) FROM archive_erasures")[0][0],
    )


# --- E1, E2: the refusal, and the Captain's way through it --------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing(tmp_path: Path, target: str) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store, citing, _unrelated = await _archive_with(tmp_path, (_CITED,))
        try:
            with pytest.raises(ArchiveCitationsBlockErasure) as refused:
                await _forget(_with_archive(rig.em, store), target)

            assert refused.value.entry_ids == (citing,)
            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased
        finally:
            await store.close()
    assert _archive_counts(tmp_path) == (2, 0)


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        store, citing, unrelated = await _archive_with(tmp_path, (_CITED,))
        try:
            runtime = _runtime(root, rig.em)
            runtime.archive_store = store  # the runtime's public accessor (7.10)
            async with _client(runtime) as client:
                refused = await _post(client, _FORGET, _TARGETS[target])

                assert refused.status_code == 409, refused.text
                assert refused.json()["error"] == "archive_entries_cite_erased_episodes"
                assert refused.json()["archive_entry_ids"] == [citing]
                assert _live(rig.em) == [_CITED, _OTHER]

                # The Captain's erasure, as the CLI runs it: its own event loop, so in a thread.
                assert await asyncio.to_thread(_erase, monkeypatch, _config(tmp_path), citing, "the Captain forgets it") == 0

                erased = await _post(client, _FORGET, _TARGETS[target])

                assert erased.status_code == 200, erased.text
                assert sorted(erased.json()["deleted_episode_ids"]) == _MATCHED[target]
                assert _live(rig.em) == sorted({_CITED, _OTHER} - set(_MATCHED[target]))
                assert await store.entry_ids_citing([_CITED]) == ()
        finally:
            await store.close()
    archive = tmp_path / "archive.db"
    assert _rows(archive, "SELECT id FROM archive") == [(unrelated,)]
    assert _rows(archive, "SELECT entry_id, reason FROM archive_erasures") == [(citing, "the Captain forgets it")]


# --- E3 to E5: what does not block, and what fails closed ----------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_erasure_no_archive_entry_cites_erases_as_before(tmp_path: Path, target: str) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store, _citing, _unrelated = await _archive_with(tmp_path, ("ep-elsewhere",))
        try:
            result = await _forget(_with_archive(rig.em, store), target)

            assert sorted(result.deleted_episode_ids) == _MATCHED[target]
            assert _live(rig.em) == sorted({_CITED, _OTHER} - set(_MATCHED[target]))
        finally:
            await store.close()
    assert _archive_counts(tmp_path) == (2, 0)


@pytest.mark.parametrize("accessor", ["mock", "none"])
async def test_the_forget_route_consults_only_a_real_archive_store(tmp_path: Path, accessor: str) -> None:
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        if accessor == "none":
            runtime.archive_store = None
        assert accessor == "none" or isinstance(runtime.archive_store, MagicMock)  # premise: the double's attribute
        async with _client(runtime) as client:
            erased = await _post(client, _FORGET, {"episode_id": _CITED})

        assert erased.status_code == 200, erased.text
        assert erased.json()["deleted_episode_ids"] == [_CITED]


_UNREADABLE = {"corrupt-row": "{x", "dict": '{"another": "ep-000"}', "string": '"ep-000"'}  # cells the read refuses


@pytest.mark.parametrize(
    ("fault", "target"),
    [
        ("closed", "episode"), ("corrupt-row", "episode"), ("dict", "episode"), ("string", "episode"),
        ("dict", "agent"), ("dict", "resource"),
    ],
    ids=["closed", "corrupt-row", "dict", "string", "dict-agent", "dict-resource"],
)
async def test_an_archive_that_cannot_answer_stops_the_erasure_before_anything_is_erased(
    tmp_path: Path, fault: str, target: str,
) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store, _citing, _unrelated = await _archive_with(tmp_path, ("ep-elsewhere",))
        if fault == "closed":
            await store.close()
        else:
            connection = sqlite3.connect(str(tmp_path / "archive.db"))
            try:
                connection.execute(
                    "INSERT INTO archive (timeline_id, category, title, content, archived_at, source_kind, "
                    "source_ref, source_episode_ids) VALUES ('t', 'c', 't', 'c', 0, 'convergence_report', 'r', ?)",
                    (_UNREADABLE[fault],),
                )
                connection.commit()
            finally:
                connection.close()
        try:
            with pytest.raises((RuntimeError, ValueError)):
                await _forget(_with_archive(rig.em, store), target)

            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased, at any entry point
        finally:
            await store.close()


# --- E6 to E8: authority, the accessor, and a citation that lands mid-run -----------------------------------------


def test_only_the_erasure_manager_reads_citations_and_only_the_forget_route_builds_it() -> None:
    builders: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ErasureManager":
                builders.add(path.relative_to(_SRC).as_posix())
    assert builders == {"routers/security.py"}
    assert _naming("entry_ids_citing") == {"knowledge/erasure.py"}
    assert _naming("erase_entry") == {"__main__.py"}  # S1's rule holds: the AD-754 route never erases an entry


def test_the_runtime_exposes_its_archive_store_read_only() -> None:
    accessor = inspect.getattr_static(ProbOSRuntime, "archive_store")
    assert isinstance(accessor, property) and accessor.fset is None
    runtime = object.__new__(ProbOSRuntime)  # no boot: only the accessor is under test
    sentinel = object()
    runtime._archive_store = sentinel
    assert runtime.archive_store is sentinel


@pytest.mark.parametrize("late", ["citation", "unreadable-cell"])
async def test_a_citation_that_appears_after_the_scan_still_stops_that_episode(tmp_path: Path, late: str) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _midway(tmp_path, unreadable=late == "unreadable-cell")
        await store.initialize()
        try:
            with pytest.raises(ErasureCascadeIncomplete) as incomplete:
                await _with_archive(rig.em, store).forget_agent_memory("agent-a")

            if late == "citation":
                assert set(incomplete.value.failures) == {_CITED}
                assert type(incomplete.value.failures[_CITED]) is ArchiveCitationsBlockErasure
                assert incomplete.value.result.deleted_episode_ids == [_OTHER]
                assert _live(rig.em) == [_CITED]
            else:  # every per-episode read meets the cell it cannot interpret, so nothing is erased (D10)
                assert set(incomplete.value.failures) == {_CITED, _OTHER}
                assert all(type(error) is ValueError for error in incomplete.value.failures.values())
                assert incomplete.value.result.deleted_episode_ids == []
                assert _live(rig.em) == [_CITED, _OTHER]
        finally:
            await store.close()


@pytest.mark.parametrize("target", ["episode", "agent", "resource", "late"])
async def test_a_refused_erasure_keeps_the_cited_episodes_attachment_and_audit_row(
    tmp_path: Path, target: str,
) -> None:
    """A2, finding M3-F1: the refusal comes before every destructive consumer, the attachment's unlink and the audit
    marking included, at each entry point and at the per-episode check (``late``: a citation lands after the scan)."""
    store = _midway(tmp_path) if target == "late" else _store(tmp_path)
    await store.initialize()
    try:
        if target != "late":
            assert await store.promote_entry(_record(source_episode_ids=(_CITED,))) is PromotionOutcome.CREATED
        async with _traced(tmp_path, store) as (rig, manager, attachments, audit):
            if target == "late":
                with pytest.raises(ErasureCascadeIncomplete) as incomplete:
                    await manager.forget_agent_memory("agent-a")

                assert type(incomplete.value.failures[_CITED]) is ArchiveCitationsBlockErasure
                assert await _traces(rig.em, attachments, audit) == ([_CITED], True, ["[DELETED]", _CITED])
            else:
                with pytest.raises(ArchiveCitationsBlockErasure):
                    await _forget(manager, target)

                assert await _traces(rig.em, attachments, audit) == ([_CITED, _OTHER], True, [_CITED, _OTHER])
    finally:
        await store.close()
```

## 8. Tracking (tracker pairs; M4's commit)

Written against `7bdd9c32`. S2 and BF-925 merge first and add their own head entries; the anchors below are text they leave in place, so they apply unchanged. If the orchestrator's re-anchoring rule applies (more entries merged), keep these anchors: they are the title line and the heading every entry so far has been inserted against. Set the date to the commit date.

**`PROGRESS.md`** (the new entry goes first, under the title):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1341 S3 (2026-10-26), #1569 slice 3 of 6 -- the Captain reviews and vetoes what is promoted into the Ship's Archive, and an AD-754 erasure never leaves an archive entry citing an erased episode.** `probos archive pending` lists every Ship's Records source the next promotion would consider, with what promoting it now would do: archive it (new, or a revision of the entry it names), nothing (already archived, with the entry's id), or never (vetoed or erased by the Captain), and what is withheld. `probos archive veto SOURCE_REF --reason TEXT` records the Captain's veto in a new content-free `archive_vetoes` table (kind, path, reason, timeline, time; one per source); `promote_entry`'s one statement honours it for the source with any content (`VETOED`), and a veto of a source already archived is refused (erase its entry instead). The queue is derived from the plan, not stored; promotion before a reset stays on by default and promotes everything not vetoed, now reporting "N vetoed by the Captain", and the dry run points to the review. An AD-754 erasure (`POST /api/security/forget`) whose matched episodes an archive entry cites now erases nothing and answers 409 with the entries' ids; the Captain erases each with `probos archive erase` and retries, so the archive gains no new deleter and no entry outlives the evidence it cites. A citation the archive cannot read stops the erasure too; an attachment another episode shares is still unlinked as before (registered). No production source cites an episode until S4, so nothing changes in practice yet. Schema stays v1 (the table is additive); the runtime gains a read-only `archive_store` accessor. New: `tests/test_ad1341_s3_veto_store.py`, `tests/test_ad1341_s3_review_cli.py`, `tests/test_ad1341_s3_erasure_cascade.py`. The contract is `prompts/ad-1341-s3-governance-queue.md`.
```

**`DECISIONS.md`** (before the `### Explicit delegation models` heading, which every entry since 2026-10-17 has been inserted against):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1341 S3 -- The Captain reviews and vetoes what is promoted into the Ship's Archive, and an AD-754 erasure never leaves an archive entry citing an erased episode (2026-10-26, #1569 slice 3 of 6)

- *Scope.* Slice 3 of #1569 (Decision item 6 and its acceptance line), three code commits and one tracker commit. Files: `knowledge/archive_store.py` (`archive_vetoes`, `veto_source`, `source_state`, `entry_ids_citing`, `VETOED`), `knowledge/archive_promotion.py` (`vetoed`, `review_promotion`), `__main__.py` (`probos archive pending` and `veto`), `knowledge/erasure.py`, `routers/security.py`, `runtime.py` (`archive_store`), the store baseline and three new tests. Contract: `prompts/ad-1341-s3-governance-queue.md`.
- *D2 (review before canon).* Opt-out: the Captain reviews the plan and vetoes any source before the reset; the reset promotes the rest. Opt-in approval behind a flag is deferred to S4, whose crew-written lessons need chain-of-command review; approval by default was rejected, because it would block or, at `--full`, destroy unapproved knowledge (Decision item 7).
- *D3-D5 (the queue and the veto).* The queue is derived from the plan and the archive's own markers, so no content is stored twice. A veto is content-free, one per source, blocks the source with any content and is kept as the record of selection. It is refused for a source already archived (a veto does not remove an entry) and moot for one erased. One statement under the store lock; no lift in this slice.
- *D6-D7.* `promote_entry` honours a veto in its one statement; the review read runs the same checks in the same order and reserves nothing. The table is added under schema v1, because a v2 file would make a reverted build refuse every tier 2 reset.
- *D8-D11 (AD-754).* An erasure whose matched episodes an archive entry cites erases nothing and is refused (409), and the Captain erases the entries by id through the CLI. The route has no authorization, so letting it erase entries would give the archive an open deleter. Only citations count, not authorship, path or content. The check runs before anything is erased (attachments and audit marking included) and again per episode; a failed read, or a citation cell that is not a JSON list of strings, stops the erasure, and no open archive means no check. An attachment blob shared with another episode is still unlinked as before (registered). Retention (#1568 S5) protects cited episodes from decay, never from the Captain's erasure.
- *Disclosed effects.* Every archive open creates `archive_vetoes`. The reset's message gains a vetoed count, and the dry run gains one line. `pending` and `veto` open the archive as `erase` does, and may create it. `/forget` can answer 409 once S4 produces citations. With the archive unavailable, an erasure proceeds unchecked (registered).
- *Reversal.* Revert the S3 commits. A reverted build ignores `archive_vetoes` (vetoed sources are promoted again at the next reset) and never refuses an AD-754 erasure; the table stays in the file, harmless.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M4's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the gate:** add a *Validation of record* bullet before AD-1341 S3's *Reversal* line (the campaign of record, its base tree, the sha256 of each §10 file and of the three new test files, and each row's first failing test), and the same as a closing §16 of this contract; then regenerate the ledger.

**`docs/development/roadmap.md`:** no row; `AD-1341` does not appear there (S2 §8).

## 9. What this does NOT change

- The archive's entries, `erase_entry` and its marker, `record_generation` and `generations`, S1's idempotence key, criteria and C1 gate, S2's label and generation numbering, and the Oracle.
- `probos reset`'s flow, tiers, pidfile, `--skip-promotion` and its refusals; `--dry-run`'s existing lines.
- `ErasureManager`'s scans, its attachment rules (BF-868, BF-869), BF-905's fail-closed live scan, AD-1340's archive erasure, `ErasureResult`, and `/forget`'s request model and 200 body. `/forget`'s missing authorization stays as it is (register R1).
- AD-754's unlink of an attachment blob that another episode also references (`knowledge/erasure.py:331-339`; register R11).
- No new flag, `EventType`, API route, config field or `.db` file; `user_version` stays 1.
- Out of scope (D18): S4's lessons, stand-down and chain-of-command review; S5's triggers and continuous promotion; S6's `--full` snapshot, description entry and clean slate; lifting a veto; bulk erasure; an archive listing by id; an HXI view.

## 10. Mutation rows (52 rows: 31 for M1, 9 for M2, 12 for M3; whole stripped lines, each occurring once in its file after §7)

One campaign on the assembled tree (M1 to M3 applied), after an unmutated baseline run of the three new test files that passes. Run each row against the named tests and restore the file before the next row. Rows S-1 and S-2, K19 and K23, K21 and K22, and E-1, E-6 and E-7 mutate the same line; restore between them.

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| K1 | M1 | `src/probos/knowledge/archive_store.py` | `"AND NOT EXISTS (SELECT 1 FROM archive_vetoes WHERE source_kind = ? AND source_ref = ?) "` | `"AND NOT EXISTS (SELECT 1 FROM archive_vetoes WHERE 0 AND source_kind = ? AND source_ref = ?) "` | `test_a_vetoed_source_is_never_archived_with_any_content` |
| K2 | M1 | `src/probos/knowledge/archive_store.py` | `return PromotionOutcome.VETOED if vetoed else PromotionOutcome.PRESENT` | `return PromotionOutcome.PRESENT` | `test_a_vetoed_source_is_never_archived_with_any_content`, `test_the_promotion_reports_a_vetoed_source_and_archives_the_rest` |
| K3 | M1 | `src/probos/knowledge/archive_store.py` | `cursor = await self._db.execute(_VETOED_SOURCE_SQL, (kind, record.source_ref))` | `cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, record.source_ref))` | `test_a_vetoed_source_is_never_archived_with_any_content` |
| K4 | M1 | `src/probos/knowledge/archive_store.py` | `"WHERE NOT EXISTS (SELECT 1 FROM archive AS a WHERE a.source_kind = ? AND a.source_ref = ?) "` | `"WHERE NOT EXISTS (SELECT 1 FROM archive AS a WHERE 0 AND a.source_kind = ? AND a.source_ref = ?) "` | `test_a_veto_that_would_change_nothing_writes_nothing`, `test_a_veto_and_a_promotion_of_one_source_never_both_succeed[promotion]` |
| K5 | M1 | `src/probos/knowledge/archive_store.py` | `"AND NOT EXISTS (SELECT 1 FROM archive_erasures AS e WHERE e.source_kind = ? AND e.source_ref = ?) "` | `"AND NOT EXISTS (SELECT 1 FROM archive_erasures AS e WHERE 0 AND e.source_kind = ? AND e.source_ref = ?) "` | `test_a_veto_that_would_change_nothing_writes_nothing` |
| K6 | M1 | `src/probos/knowledge/archive_store.py` | `"ON CONFLICT (source_kind, source_ref) DO NOTHING"` | `"ON CONFLICT (source_kind, source_ref) DO UPDATE SET reason = excluded.reason"` | `test_a_veto_that_would_change_nothing_writes_nothing` |
| K7 | M1 | `src/probos/knowledge/archive_store.py` | `CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_vetoes_source ON archive_vetoes(source_kind, source_ref);` | `CREATE INDEX IF NOT EXISTS idx_archive_vetoes_source ON archive_vetoes(source_kind, source_ref);` | `test_the_archive_has_a_content_free_veto_table_keyed_by_source`, `test_a_vetoed_source_is_never_archived_with_any_content` |
| K8 | M1 | `src/probos/knowledge/archive_store.py` | `return VetoOutcome.ERASED if was_erased else VetoOutcome.ALREADY_VETOED` | `return VetoOutcome.ALREADY_VETOED` | `test_a_veto_that_would_change_nothing_writes_nothing` |
| K9 | M1 | `src/probos/knowledge/archive_store.py` | `if archived:` | `if False:` | `test_a_veto_that_would_change_nothing_writes_nothing` |
| K10 | M1 | `src/probos/knowledge/archive_store.py` | `if type(source_kind) is not SourceKind:` | `if False:` | `test_a_veto_needs_a_kind_a_source_and_a_reason` |
| K11 | M1 | `src/probos/knowledge/archive_store.py` | `return SourceState(PromotionOutcome.ERASED, entry_ids)` | `return SourceState(PromotionOutcome.CREATED, entry_ids)` | `test_the_review_reads_what_promote_entry_then_does`, `test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing` |
| K12 | M1 | `src/probos/knowledge/archive_store.py` | `return SourceState(PromotionOutcome.VETOED, entry_ids)` | `return SourceState(PromotionOutcome.CREATED, entry_ids)` | `test_the_review_reads_what_promote_entry_then_does`, `test_a_veto_or_erasure_after_the_review_decides_the_promotion` |
| K13 | M1 | `src/probos/knowledge/archive_store.py` | `return SourceState(PromotionOutcome.PRESENT if present else PromotionOutcome.CREATED, entry_ids)` | `return SourceState(PromotionOutcome.CREATED, entry_ids)` | `test_the_review_reads_what_promote_entry_then_does` |
| K14 | M1 | `src/probos/knowledge/archive_store.py` | `entry_ids = tuple(row[0] for row in await cursor.fetchall())` | `entry_ids = ()` | `test_the_review_reads_what_promote_entry_then_does`, `test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing` |
| K15 | M1 | `src/probos/knowledge/archive_store.py` | `if wanted.intersection(cited):` | `if False:` | `test_the_entries_citing_an_episode_are_found_in_id_order` |
| K16 | M1 | `src/probos/knowledge/archive_store.py` | `wanted = {item for item in episode_ids if item}` | `wanted = set()` | `test_the_entries_citing_an_episode_are_found_in_id_order` |
| K17 | M1 | `src/probos/knowledge/archive_store.py` | `raise RuntimeError("AD-1341 S3: the Ship's Archive is not open, so its citations cannot be read")` | `return ()` | `test_the_citation_read_never_answers_none_when_it_cannot_read` |
| K18 | M1 | `src/probos/knowledge/archive_store.py` | `if type(episode_ids) not in (list, tuple) or any(type(item) is not str for item in episode_ids):` | `if False:` | `test_the_citation_read_never_answers_none_when_it_cannot_read` |
| K19 | M1 | `src/probos/knowledge/archive_store.py` | `_CITING_SQL = "SELECT id, source_episode_ids FROM archive WHERE source_episode_ids IS NOT '[]' ORDER BY id"` | `_CITING_SQL = "SELECT id, source_episode_ids FROM archive WHERE source_episode_ids IS NOT '[]' ORDER BY id DESC"` | `test_the_entries_citing_an_episode_are_found_in_id_order` |
| K20 | M1 | `src/probos/knowledge/archive_store.py` | `cited = json.loads(cell) if type(cell) is str else None  # SQL NULL, or a blob, is no citation list (D10)` | `cited = json.loads(cell) if type(cell) is str else []` | `test_the_citation_read_never_answers_none_when_it_cannot_read[sql-null]` |
| K21 | M1 | `src/probos/knowledge/archive_store.py` | `if type(cited) is not list or any(type(item) is not str for item in cited):` | `if False:` | `test_the_citation_read_never_answers_none_when_it_cannot_read[dict]`, `test_the_citation_read_never_answers_none_when_it_cannot_read[string]` |
| K22 | M1 | `src/probos/knowledge/archive_store.py` | `if type(cited) is not list or any(type(item) is not str for item in cited):` (after K21 is restored) | `if type(cited) is not list:` | `test_the_citation_read_never_answers_none_when_it_cannot_read[number-list]`, `test_the_citation_read_never_answers_none_when_it_cannot_read[mixed-list]` |
| K23 | M1 | `src/probos/knowledge/archive_store.py` | `_CITING_SQL = "SELECT id, source_episode_ids FROM archive WHERE source_episode_ids IS NOT '[]' ORDER BY id"` (after K19 is restored) | `_CITING_SQL = "SELECT id, source_episode_ids FROM archive WHERE source_episode_ids NOT IN ('', '[]') ORDER BY id"` | `test_the_citation_read_never_answers_none_when_it_cannot_read[empty-text]`, `test_the_citation_read_never_answers_none_when_it_cannot_read[sql-null]` |
| K24 | M1 | `src/probos/knowledge/archive_store.py` | `async with self._write_lock:  # AD-1341 S3: the veto and its checks commit or roll back alone (D16)` | `if True:` | `test_a_write_whose_commit_fails_leaves_nothing_the_other_write_can_commit` |
| K25 | M1 | `src/probos/knowledge/archive_store.py` | `async with self._write_lock:  # AD-1341 F1: the insert and its erasure check commit or roll back alone` | `if True:` | `test_a_write_whose_commit_fails_leaves_nothing_the_other_write_can_commit` |
| K26 | M1 | `src/probos/knowledge/archive_store.py` | `await _rollback_quietly(self._db)  # AD-1341 S3: nothing is left open for the next write` | `pass` | `test_a_write_whose_commit_fails_leaves_nothing_the_other_write_can_commit[veto-fails]` |
| P1 | M1 | `src/probos/knowledge/archive_promotion.py` | `elif outcome is PromotionOutcome.VETOED:  # AD-1341 S3: the Captain's veto, reported, never archived` | `elif False:` | `test_the_promotion_reports_a_vetoed_source_and_archives_the_rest` |
| P2 | M1 | `src/probos/knowledge/archive_promotion.py` | `vetoed.append(record.source_ref)` | `present.append(record.source_ref)` | `test_the_promotion_reports_a_vetoed_source_and_archives_the_rest` |
| P3 | M1 | `src/probos/knowledge/archive_promotion.py` | `vetoed=tuple(vetoed),` | `vetoed=(),` | `test_the_promotion_reports_a_vetoed_source_and_archives_the_rest`, `test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew` |
| P4 | M1 | `src/probos/knowledge/archive_promotion.py` | `sources = [PendingSource(record, await archive.source_state(record)) for record in plan.records]` | `sources = []` | `test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing` |
| P5 | M1 | `src/probos/knowledge/archive_promotion.py` | `return PromotionReview(sources=tuple(sources), withheld=plan.withheld)` | `return PromotionReview(sources=tuple(sources), withheld=())` | `test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing` |
| C-1 | M2 | `src/probos/__main__.py` | `return _cmd_archive_pending(args)` | `return 2` | `test_pending_shows_what_the_next_promotion_would_do_with_each_source` |
| C-2 | M2 | `src/probos/__main__.py` | `return _cmd_archive_veto(args)` | `return 2` | `test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew`, `test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing` |
| C-3 | M2 | `src/probos/__main__.py` | `record = next((item for item in plan.records if item.source_ref == source_ref), None)` | `record = next(iter(plan.records), None)` | `test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing` |
| C-4 | M2 | `src/probos/__main__.py` | `if outcome is VetoOutcome.ARCHIVED:` | `if False:` | `test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing` |
| C-5 | M2 | `src/probos/__main__.py` | `f"{len(promoted.erased)} erased by the Captain, {len(promoted.vetoed)} vetoed by the Captain, "` | `f"{len(promoted.erased)} erased by the Captain, "` | `test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew` |
| C-6 | M2 | `src/probos/__main__.py` | `if not confirmed and input("  Veto its promotion into the Ship's Archive? [y/N]: ").strip().lower() != "y":` | `if False:` | `test_a_veto_that_cannot_or_need_not_happen_vetoes_nothing` |
| C-7 | M2 | `src/probos/__main__.py` | `return "x vetoed by the Captain"` | `return "+ would be promoted"` | `test_pending_shows_what_the_next_promotion_would_do_with_each_source`, `test_a_vetoed_source_survives_two_resets_without_reaching_the_archive_or_a_later_crew` |
| C-8 | M2 | `src/probos/__main__.py` | `if plan.records:  # AD-1341 S3: the Captain reviews, and may veto, before the reset promotes` | `if False:` | `test_the_dry_run_points_the_captain_to_the_review` |
| C-9 | M2 | `src/probos/__main__.py` | `if not config.archive.enabled:  # AD-1341 S3: a disabled archive is never opened, so pending creates no file` | `if False:` | `test_pending_refuses_a_disabled_archive_and_creates_no_file` |
| E-1 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, [episode_id])  # AD-1341 S3: before anything is erased` | `pass` | `test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing`, `test_a_citation_that_appears_after_the_scan_still_stops_that_episode` |
| E-2 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: a resource's matches` | `pass` | `test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing` |
| E-3 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: an agent's matches` | `pass` | `test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing`, `test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes` |
| E-4 | M3 | `src/probos/knowledge/erasure.py` | `if citing:` | `if False:` | `test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing` |
| E-5 | M3 | `src/probos/knowledge/erasure.py` | `self._archive_store = archive_store` | `self._archive_store = None` | `test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing`, `test_an_archive_that_cannot_answer_stops_the_erasure_before_anything_is_erased` |
| E-6 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, [episode_id])  # AD-1341 S3: before anything is erased` (after E-1 is restored) | `await self._delete_attachments(await self._attachment_ids_for_episode(episode_id)); await _refuse_while_the_archive_cites(self._archive_store, [episode_id])` | `test_a_refused_erasure_keeps_the_cited_episodes_attachment_and_audit_row[episode]`, `test_a_refused_erasure_keeps_the_cited_episodes_attachment_and_audit_row[late]` |
| E-7 | M3 | `src/probos/knowledge/erasure.py` | `await _refuse_while_the_archive_cites(self._archive_store, [episode_id])  # AD-1341 S3: before anything is erased` (after E-6 is restored) | `await self._audit_log.mark_deleted(episode_id) if self._audit_log is not None else None; await _refuse_while_the_archive_cites(self._archive_store, [episode_id])` | `test_a_refused_erasure_keeps_the_cited_episodes_attachment_and_audit_row[episode]`, `test_a_refused_erasure_keeps_the_cited_episodes_attachment_and_audit_row[late]` |
| S-1 | M3 | `src/probos/routers/security.py` | `archive_store=archive if isinstance(archive, ArchiveStore) else None,  # AD-1341 S3: a real store, or none` | `archive_store=None,` | `test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes` |
| S-2 | M3 | `src/probos/routers/security.py` | `archive_store=archive if isinstance(archive, ArchiveStore) else None,  # AD-1341 S3: a real store, or none` (after S-1 is restored) | `archive_store=archive,` | `test_the_forget_route_consults_only_a_real_archive_store` |
| S-3 | M3 | `src/probos/routers/security.py` | `status_code=409,` | `status_code=200,` | `test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes` |
| S-4 | M3 | `src/probos/routers/security.py` | `"archive_entry_ids": list(exc.entry_ids),` | `"archive_entry_ids": [],` | `test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes` |
| R-1 | M3 | `src/probos/runtime.py` | `return self._archive_store` | `return None` | `test_the_runtime_exposes_its_archive_store_read_only` |

The row count in the heading includes S-2, K22, K23, E-6 and E-7. K24 and K25 remove the store lock from `veto_source` and `promote_entry` (`if True:` keeps the body's indentation) and K26 the veto's rollback. V7 cannot see them (aiosqlite serialises the statements, and `gather` lets the first task take the lock before the second runs), so V7b pauses the first write's commit, starts the second and then fails the first: under K24 or K25 the second write finishes within V7b's 0.2 s wait (it takes milliseconds), and under K26 it commits what the failed veto left open. The unmutated V7b does not depend on that timing: the lock alone holds the second write back. K26's and C-9's anchors carry an inline comment added in A2, so that each is unique in its file. Mutation K17 targets the one `RuntimeError` text unique to `entry_ids_citing`; `veto_source` and `source_state` reuse S1's `"ArchiveStore not initialized"` line, which occurs several times and has no row.

## 11. Verified Against Codebase (2026-10-26, HEAD `7bdd9c32`, tree `54c086ffc33b64aa9dbe413575fb3ad89950071e`)

Read with the Grep and Read tools on this checkout. Every SEARCH block above was copied from these reads.

```
src/probos/knowledge/archive_store.py
  3-9: "Stores curated knowledge entries ... ``archive_erasures`` that holds no title, content or hash."   (7.1 pair 1)
  11-15: "Each entry records the timeline ..."   (S2's pair 1; untouched here)
  26-37: imports: asyncio, hashlib, json, logging, time, dataclass, field, StrEnum, Any, ConnectionFactory
  87-92: class PromotionOutcome(StrEnum): CREATED, PRESENT ("# this source with this content ..."), ERASED (...)   (pair 2)
  95-102: class GenerationOutcome ... PROMOTED = "promoted" / SKIPPED = "skipped" / (2 blank) / def _required_text   (pair 3)
  102-104: _required_text raises ValueError("AD-1341: {name} must be a non-empty string")
  107-151: PromotionRecord (frozen; validates exact types; source_episode_ids: tuple[str, ...] = ())
  185-227: _SCHEMA ... CREATE INDEX IF NOT EXISTS idx_archive_erasures_source ON archive_erasures(source_kind, source_ref); """   (pair 4)
  237: ("source_episode_ids", "TEXT NOT NULL DEFAULT '[]'")
  255-265: # One statement, so an erasure can never land ... _PROMOTE_SQL = (... ) / (blank) / _ERASED_SOURCE_SQL = ...   (pair 5)
  283-286: _valid_reason (1..500, stripped)
  305-317: class ArchiveStore docstring "... the three writes and ``close`` hold ``_write_lock`` ..."   (pair 6)
  324: self._write_lock = asyncio.Lock()
  381-406: promote_entry: params tuple ending "json.dumps(list(record.source_episode_ids)), kind, record.source_ref,"; classification   (pairs 7, 8)
  427-455: erase_entry ... logger.warning("AD-1341: the Captain erased Ship's Archive entry %d", entry_id) / return True   (pair 9)
  457: async def entry_by_id(self, entry_id: int) -> ArchiveEntry | None:
  522-540: _row_to_entry (S2 changes its signature; S3 never calls it)
src/probos/knowledge/archive_promotion.py
  13-15: "- Ship's Records carry no source-episode ids ... adds them).\n"""   (7.2 pair 1)
  23-29: from probos.knowledge.archive_store import ( PROMOTABLE_CLASSIFICATIONS, ArchiveStore, PromotionOutcome, PromotionRecord, SourceKind, )   (pair 2)
  83-98: PromotionPlan (records, withheld); PromotionReport (created, present, erased, withheld)   (pair 3)
  101-146: plan_promotion(records, *, timeline_id) -> PromotionPlan
  158-177: promote_ship_records body; return PromotionReport( created=..., withheld=plan.withheld, )   (pairs 4, 5; end of file)
src/probos/__main__.py
  64-69: if TYPE_CHECKING: import httpx / SystemConfig / ArchiveStore / RecordsStore   (7.6 pair 1)
  72: def _default_data_dir() -> Path:
  2931-2934: config, _ = _load_config_with_fallback(getattr(args, 'config', None)); data_dir = getattr(args, 'data_dir', None) or _default_data_dir()
  2974-2978: --dry-run: _show_dry_run; tier >= 2: return _show_promotion_plan(...)
  3165: _UNATTRIBUTED_TIMELINE = "(no instance id)"
  3179-3188: _read_instance_id(data_dir) -> str
  3191-3197: _reset_records_store(config, data_dir)
  3200-3212: _configured_archive_store(config) (creates only the default's directory)
  3306-3318: promote_ship_records(...); record_generation(closed); return True, (f"Ship's Archive: ... withheld (timeline {timeline_id}).")   (pair 2)
  3346-3354: dry-run plan prints: "+ {ref}", "- withheld: {path}", then "if plan.records and not timeline_id:"   (pair 3)
  3357-3385: _cmd_archive: "if getattr(args, "archive_cmd", None) != "erase":" usage, return 2; config; enabled; id; reason   (pair 4)
  3388-3412: _erase_archive_entry ... print(f"Erased Ship's Archive entry {entry_id}. ...") / return 0   (pair 5)
  3415: def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
  3436-3452: root parser --config (default None) and --data-dir (default None)
  3729-3743: archive parser, archive_sub (dest archive_cmd), archive_erase ... --config SUPPRESS / (blank) / args = parser.parse_args()   (pairs 6, 7)
  3802-3804: if args.command == "archive": sys.exit(_cmd_archive(args))
src/probos/knowledge/erasure.py
  11-14: from typing import Any / (blank) / from probos.security.audit_log import AuditLog / from probos.types import EvictionDisposition   (7.8 pair 1)
  68-84: class ErasureCascadeIncomplete ... self.result / self.failures / self.enumeration_error   (pair 2)
  99-108: class ErasureManager.__init__(episodic_memory, attachment_store, audit_log)   (pair 3)
  110-138: forget_episode: attachment_ids = ... first; evict_by_ids(..., disposition=ERASE)   (pair 4)
  140-152: forget_resource   (pair 5);  154-164: forget_agent_memory   (pair 6)
  203-233: _forget_all: catches Exception per episode, then raises ErasureCascadeIncomplete
  93: "``ErasureManager`` stays within the SRP review trigger of 15 direct methods" (15 methods today)
src/probos/routers/security.py
  25-27: crew_scope_token / ErasureManager / require_crew_scope imports   (7.9 pair 1)
  77-106: @router.post("/forget") request_erasure(request, runtime=Depends(get_runtime)); manager = ErasureManager(...); dispatch; return body   (pairs 2-4)
  315: raise HTTPException(status_code=409, detail=str(exc)) from exc   (restore route; a different line from S-3's)
src/probos/routers/auth.py
  31-72: require_crew_scope: a pass-through when no token resolves
src/probos/api.py
  272, 318, 347: security router included; the only middleware is CORS (:200)
src/probos/runtime.py
  462: class ProbOSRuntime:
  602: _archive_store: Any | None;  1361: self._archive_store = None;  2999: self._archive_store = cog.archive_store
  2208-2211: @property def records_store(self): """Ship's Records service (AD-434).""" return self._records_store   (7.10)
src/probos/startup/shutdown.py
  2064-2074: closes runtime._archive_store, then sets it None
src/probos/knowledge/records_store.py
  211-225: write_entry(author, path, content, message, *, classification="ship", status="draft", ..., extra_frontmatter)
  415-421: append_captains_log -> captains-log/{today}.md
  450-508: write_notebook(callsign, topic_slug, content, *, classification, extra_frontmatter) -> notebooks/{callsign}/{topic_slug}.md
docs/development/store-baseline.yaml
  121-125: - module: probos.knowledge.archive_store / tables: archive, archive_erasures, generations   (7.3)
tests/test_ad1341_s1_archive_store.py
  51-60: _store(tmp_path), _rows(path, sql, params);  63-74: _record(**overrides);  77-90: _plant_v0(path, *, extra_column=False)
  107-108: tables check is a subset (<=), so a new table passes
  242-252: the pinned public surface   (7.4)
tests/test_ad1341_s1_reset_and_erase.py
  49-51: _SHIP, _NEXT_SHIP, _CONVERGENCE;  162-166: _config;  169-178: _data_dir;  181-197: _records, _write_records
  200-209: _archive_store, _rows;  212-221: _reset;  224-228: _erase (archive_cmd="erase");  235-240: _oracle_query
  479-480: "2 to promote, 1 withheld" and "+ captains-log/" asserted (kept by 7.6 pair 3)
  560-562: generations columns created_count, present_count, erased_count (withheld_count exists: archive_store.py:209)
  590-601: R11 census (erase_entry and record_generation only in __main__.py; S3 keeps it true)
  618-644: the main() dispatch test pattern C4 follows
tests/test_ad1341_s1_promotion.py
  256: report == PromotionReport(created=(), present=(), erased=(), withheld=())   (kept equal by the default)
tests/test_ad1340_s1_eviction.py
  62-76: _episode(i) (agent_ids ["agent-a"]), _ids;  87-101: _memory(root, mode, *, max_episodes=100);  121-123: _raw
tests/test_ad1340_s2a_lookup_route.py
  47-48: _TOKEN, _AUTH;  200-210: _runtime(root, memory, *, token="") -> MagicMock;  213-219: _client;  222-234: _post
  635-658: RT-g posts /forget with no auth header (unchanged by S3: no authorization added)
tests/test_ad1340_s2b_restore_route.py
  540-543: posts /forget with no auth header (unchanged)
tests/test_bf905_erasure_live_scan.py
  86-91: _route_client uses _runtime(root, em) (no token); 310: ErasureManager(memory, None, None) positional
scripts/phantom_api_ast_helper.py
  122-124: _CALL_RE matches receiver.method(...) only; 237-241: a method absent from src is skipped by the kwarg check
logs/ad1341s3/ad1341s2-contract.md
  135-325: S2's archive_store.py pairs 1-8;  444-480: S2's runtime.py pair;  850-894: S2's tracker pairs
```

## Absence Verified (2026-10-26)

**S3-AV1.** CLAIM: no review, veto or pending state exists for an archive promotion, and the new names are free.
RUN: Grep `PendingSource|PromotionReview|SourceState|VetoOutcome|veto_source|source_state\b|entry_ids_citing|archive_vetoes|ArchiveCitationsBlockErasure|_refuse_while_the_archive_cites|_cmd_archive_pending|_cmd_archive_veto|review_promotion` over `src/`, `tests/`, `scripts/`, `docs/`.
FOUND: no match.
HOLDS: yes.

**S3-AV2.** CLAIM: no API route reads or writes the Ship's Archive; its Captain surface is the CLI.
RUN: Grep `archive_store|ArchiveStore` in `src`.
FOUND: `archive_promotion.py`, `archive_store.py`, `runtime.py:602, 1361, 2999`, `__main__.py:68, 3200-3212, 3297, 3390`, `startup/cognitive_services.py:670-707, 785`, `startup/results.py:140`, `startup/shutdown.py:2064-2074`, `cognitive/oracle_service.py:340, 354, 632, 1138`. No `routers/` file.
HOLDS: yes.

**S3-AV3.** CLAIM: `ErasureManager` is built in `src` only by `routers/security.py`, and no HXI or CLI calls `/api/security/forget`.
RUN: Grep `ErasureManager|forget_agent_memory|forget_resource|forget_episode` in `src`; Grep `security/forget` over the repository excluding `tests/`.
FOUND: `routers/security.py:26, 83, 90, 92, 94`; `knowledge/erasure.py` (definitions and docstrings); `perception/consumer.py:1083` (a comment). `security/forget` only in `prompts/`, `PROGRESS.md`, `DECISIONS.md`.
HOLDS: yes.

**S3-AV4.** CLAIM: no `src` producer writes a non-empty `source_episode_ids`, and AD-1340's citation retention is not built.
RUN: Grep `source_episode_ids|archive.*cites|cited_episode|AD-1340 S5` in `src`.
FOUND: only `archive_store.py:61, 124, 137-140, 237, 252, 259, 388, 539` (the field, its validation, its column and its round trip); `archive_promotion.py` builds `PromotionRecord` without it (`:129-145`).
HOLDS: yes.

**S3-AV5.** CLAIM: the runtime exposes no archive accessor; nothing reads a public `archive_store` on the runtime.
RUN: Grep `\.archive_store\b|return self\._archive_store` in `src`; Grep `def records_store|def attachment_store|_archive_store` in `runtime.py`.
FOUND: `runtime.py:2999` (`cog.archive_store`, the startup result's field); properties `records_store` (`:2209`) and `attachment_store` (`:2269`); no `archive_store` property.
HOLDS: yes.

**S3-AV6.** CLAIM: `PromotionOutcome` and `PromotionReport` have no consumer in `src` beyond the store, the service and the reset's message.
RUN: Grep `PromotionOutcome|PromotionReport` in `src`; Grep `PromotionReport\(|\.erased\b|PromotionOutcome\.` in the archive tests.
FOUND: `archive_store.py` (definition, `promote_entry`), `archive_promotion.py:26, 92, 151, 164, 166, 175`; `__main__.py:3306-3318` reads `promoted.created/present/erased/withheld`. Tests: identity comparisons and `test_ad1341_s1_promotion.py:223, 256, 274` (the default keeps `:256` equal).
HOLDS: yes.

**S3-AV7.** CLAIM: no test pins the reset's promotion message or the dry run's line count, so pairs 2 and 3 of 7.6 break no test.
RUN: Grep `erased by the Captain|already archived,|withheld \(timeline` in `tests`; Grep `to promote|withheld: |Ship's Archive plan` in `tests`.
FOUND: no message pin; `test_ad1341_s1_reset_and_erase.py:479` (`"2 to promote, 1 withheld" in out`, a substring that pair 3 keeps).
HOLDS: yes.

**S3-AV8.** CLAIM: the mutation rows' lines are new, so each occurs once after §7.
RUN: Grep `status_code=409` in `routers/security.py`; Grep `return self\._archive_store` in `runtime.py`; Grep `if citing|if archived` in `knowledge/`.
FOUND: `security.py:315` only (`raise HTTPException(status_code=409, detail=str(exc)) from exc`, a different stripped line); none for the rest.
HOLDS: yes, with S2 applied too: S2's REPLACE text adds none of these lines (S2 §10 lists its new lines).

**S3-AV9.** CLAIM: no test calls `/forget` in a way S3 changes.
RUN: Grep `api/security/forget|request_erasure` in `tests`; Grep `forget` in the two seam files.
FOUND: `test_bf905_erasure_live_scan.py:287, 298` (no archive: MagicMock runtime), `test_ad1340_s2a_lookup_route.py:45, 648`, `test_ad1340_s2b_restore_route.py:540` (no citing entry; no authorization change).
HOLDS: yes. Each passes a `MagicMock` runtime, whose `archive_store` the route ignores (E4 holds that).

## Not verified (the orchestrator verifies by running)

1. **The live archive** (`%LOCALAPPDATA%\ProbOS\archive\archive.db`, read-only, the vessel stays up): `PRAGMA user_version` (1), `SELECT count(*) FROM archive` (0). After the first boot on the merged build, `sqlite_master` lists `archive_vetoes` and `idx_archive_vetoes_source`. The bridge allows no `sqlite3`; I did not open it.
2. **The phantom precheck** on this contract: `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-1341-s3-governance-queue.md`. I traced `_CALL_RE` and the kwarg check against the blocks (§12) but could not run `pwsh`.
3. **`write_entry` on an existing path replaces the content** (V9 and C2 revise `_CONVERGENCE`). The tests assert the effect: V9's `revised` state would read PRESENT if the write did not replace the content.
4. **E2's two connections** (the route's store in the test loop, the CLI's in a thread with its own loop) on one SQLite file: the erasure's commit is seen by the route's next read. Expected from SQLite's file locking; not run.
5. **Wall time** of the M3 file: each test builds a real ChromaDB-backed memory (as the AD-1340 tests do); expected to take seconds per case.
6. **Command-policy coverage:** whether an agent's `run_command` can invoke `probos archive veto` or `erase` (the Captain-only CLI). This is S1's surface too; not verified here (register R8).

**A2 (2026-10-26), verified on the S3 candidate `6703502c` (tree `5c189230e26518e0e9a0c62994d3c1ca05794e06`):**
- `knowledge/archive_store.py:337` `_CITING_SQL ... NOT IN ('', '[]')`; `:668-672` `entry_ids_citing` passes `json.loads(cited)` to `set.intersection`; `:289` the v1 column `TEXT NOT NULL DEFAULT '[]'`; `:477-481` the migration adds only missing columns, so a citation column that already exists keeps its declaration (V6b `[sql-null]`).
- `knowledge/archive_store.py:516` and `:607`: the two lock lines, each once; `:621` the veto's rollback, one of five identical `await _rollback_quietly(self._db)` lines (`:530`, `:553`, `:577`, `:582`, `:621`), so A2 adds its comment; `:413-418` `_rollback_quietly` executes `ROLLBACK`.
- `knowledge/erasure.py:151-153` the refusal, then the attachment ids and the unlink; `:164-165` the audit marking; `:249-258` `_forget_all` records any `Exception` per episode; `:331-339` `_delete_attachments` unlinks each id and checks no other owner (R11).
- `routers/security.py:63-66` `_get_audit_log` uses the runtime's `_assistant_audit_log` when it is an `AuditLog`; `:89-95` the manager takes `attachment_store` from the runtime.
- `security/audit_log.py:28` `AuditLog(db_path, retention_days=90)`; `:32-40` `log_intent(intent, resource, actor, success, ...)`; `:62` `query`; `:96-109` `mark_deleted` sets `resource = '[DELETED]'` where it is `LIKE` the marker. `attachments/filesystem_store.py:192` `close`; `:311-318` `write(content_hash, blob, mime, *, origin=...)`; `:386` `exists`. `storage/sqlite_factory.py:18` `connect(self, db_path, *, read_only=False)`.
- `__main__.py` on the M1 base (`072adb71`) `:3367-3369`: every sub-command but `erase` prints the usage line and returns 2; on the candidate `:3440-3442` (pending) and `:3504-3513` (veto) print the refusal texts C3 and C7 assert.
- `tests/test_ad1341_s1_archive_store.py:33-47` `_V0_SCHEMA` has no citation column, `:77-90` `_plant_v0`; `tests/test_ad1341_s1_reset_and_erase.py:162` `_config(..., archive_enabled=...)`; `tests/test_ad1340_s1_eviction.py:62-72` `_episode` (ids `ep-000`, `ep-001`; one outcome), `:88-117` `_memory`.
- Absence: `_CITING_SQL|entry_ids_citing` over `src`, `tests` and `scripts` finds `archive_store.py:16, 337, 653, 662, 668`, `erasure.py:111` and, in tests, only the three S3 files and S1's A7 pin; `if not config\.archive\.enabled|_CITING_SQL|_rollback_quietly|_write_lock` over the AD-1341 tests finds no pin of a changed line.

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 1 (`runtime.X`) | `runtime.archive_store` (the tests' MagicMock assignment, E2 and E4) resolves: `archive_store` occurs as `archive_store:` and `archive_store=` in `src` (`startup/results.py:140`, `cognitive_services.py:707`), and 7.10 adds the property. The route reads it with `getattr`, not as `runtime.X` |
| Pattern 2 (`Name.attr`) | Enum members are upper case (`PromotionOutcome.VETOED`, `VetoOutcome.ARCHIVED`, `SourceKind.PUBLISHED_REPORT`). The test builds the runtime with `object.__new__(ProbOSRuntime)`, so no `ProbOSRuntime.__new__` receiver appears |
| Pattern 3 (`Name(`) | Capitalised calls are ProbOS classes that exist (`ErasureManager`, `ArchiveStore` as a base class, `JSONResponse`) or classes this contract defines (`SourceState`, `PendingSource`, `PromotionReview`, `ArchiveCitationsBlockErasure`), stdlib exceptions (`RuntimeError`, `TypeError`, `ValueError`) and `Path`. `_CitedMidway`, `_Namespace`, `_PausedCommit` and `_PausedCommitFactory` start with an underscore. A2's `FilesystemAttachmentStore(` and `AuditLog(` are classes that exist (`attachments/filesystem_store.py`, `security/audit_log.py:25`). The SQL uses `EXISTS (` and `CONFLICT (` with a space, and no upper-case SQL function is spelled `NAME(` |
| Pattern 2, the one candidate the script reports (added by the orchestrator, 2026-10-26) | `LessonsLearnedTrackingProcess.aspx`, the last path segment of the NATO lessons-learned URL in §13's prior art: a URL, not a symbol, which pattern 2 reads as `Name.attr`. The script (`scripts/phantom-api-precheck.ps1` on this file) exits 1 with exactly this one candidate and no other; no code, test or decision names it |
| Kwarg check (`receiver.method(kw=)`) | `archive.veto_source(..., timeline_id=...)` and `store.veto_source(..., timeline_id=...)`: the method is absent from the base, so the helper skips it (`phantom_api_ast_helper.py:237-241`). `writer.write_entry(...)` and `writer.write_notebook(...)` use existing keywords (`records_store.py:211-225, 450-461`). The new `archive_store=` and `vetoed=` keywords appear only in unbalanced fragments (7.9 pair 3, 7.2 pair 5) or as a mapping (`_with_archive`), as S2 did for `generation=` |
| Method check (pattern B) | No `x = Class(...)` precedes a new-method call: stores come from `_store`, `_archive_store`, `_midway` and `_configured_archive_store`; the manager from `_with_archive`. A2's `_paused_store` builds V7b's store, and E9's `_traced` builds the real attachment store and audit log, calling only methods that exist (`write`, `exists`, `close`; `log_intent`, `query`) |
| Layer | `knowledge/erasure.py` imports `knowledge.archive_store` (same layer); `routers/security.py` imports `knowledge` (as it already imports `knowledge.erasure`); `__main__.py` imports at function level, as S1 does |
| Store registry | Rule 11: 7.3 adds `archive_vetoes`; run `scripts/check_store_registry.py --check` in M1 |
| `.db` literals, config facade | no new `.db` literal, config field or `probos.config` name |
| AD-1343 census | no new name in `STOP_CALLEES`, `GUARD_CALLEES` or `RECORDED`; no `.complete(`, `.finalize(` or `.report(` call; both census files are in the M1 to M3 gates |
| SRP | `ErasureManager` stays at 15 methods (the check is a module function); `ArchiveStore` grows by three methods (to 15 with `__init__`) |
| BF-919 isolation | every archive in the new tests lies under `tmp_path` |
| Hidden pins | S1 A7 (7.4); `test_ad1341_s1_promotion.py:256` (the default); `test_ad1341_s1_reset_and_erase.py:479-480` (kept); `test_ad1025b_path_anchoring.py` pins `_install_root` and `_get_audit_log`, both unchanged |
| Size | `archive_store.py` +125 lines (to about 665); `archive_promotion.py` +40; `__main__.py` +135; `erasure.py` +40; `security.py` +25; `runtime.py` +9; the tests about 330, 230 and 260 |

## 13. Prior Art and Blind Spots

**Date used for overdue rows:** 2026-10-26.

**Internal work used:**
- S1 D7 (the content-free erasure marker keyed on kind and ref, never the hash) and D16 (the store lock). The veto copies both (D4, D5).
- `docs/research/coral-governed-memory-absorption.md:42, 53, 69` (Governed Collaborative Memory, reviewed 2026-10-25): "Failed versions and rejected candidates are not administrative noise; they are evidence that selection occurred". Adopted: the veto record is permanent and kept (D4). Its "supersede, never erase" row is AD-1340's rule; S3 keeps the Captain's erasure as the one exception, as #1569 item 6 requires.
- BF-868 and BF-905 (under-erasing is the worse failure; erase every match, then report). Adapted: S3 refuses the whole erasure before anything is erased, because erasing first would strand citing entries where no retry can find them (D8 D, D10).
- AD-1340 S2a (never serve the archive through an open gate). It is the reason the open `/forget` route never erases entries (D8 B).
- #1569 comment 1 (review before canon through the chain of command): deferred to S4, where lessons are written (D2 B).

**External prior art:**
- Datomic excision: permanent removal by predicate, requested as a transaction; "Every excision creates a permanent record", and the excision record itself cannot be excised; "Excision should never be used to correct erroneous data". This confirms S1's model (erasure leaves a protected marker) and the split S3 keeps: a veto stops what has not been archived, and erasure, not correction, removes what has. <https://docs.datomic.com/operation/excision.html>
- Wikipedia pending changes protection: edits by new or unregistered editors stay hidden until a reviewer accepts them, while autoconfirmed editors' edits go live. Adopted as the rationale for D2: review is opt-out for sources already governed when they were written, and opt-in review is for the less-trusted author (S4's lessons). <https://www.Wikipedia.com/wiki/Wikipedia:PC>, <https://meta.wikimedia.org/wiki/Flagged_Revisions>
- NATO's lessons-learned tracking process: an "Observation Submitted" is verified by an assigned reviewer before it becomes an Observation, and rejected entries are archived with a justification. Adopted: the veto keeps its reason (D4). The submitted-then-validated workflow is S4's. <https://nllp.jallc.nato.int/help/Pages/LessonsLearnedTrackingProcess.aspx>
- Erasure in derived copies (secondary, vendor and practitioner sources): a cascade covers the primary store, and copies in caches, logs and derived stores must each be erased. Adopted as the reason the citation check exists (an archive entry is a derived copy of its episodes). Crypto-shredding was considered and rejected: the archive's entries are plain text by design (S1), and `secure_delete` already overwrites erased bytes. <https://red-gate.com/simple-talk/data-security-privacy-compliance/how-to-delete-personal-data-gdpr-ccpa-compliance>, <https://www.ethyca.com/guides/right-to-be-forgotten-erasure-infrastructure>
- `docs/research/reference-projects.md`: none of its rows is a review-or-erasure system. The overdue memory rows (Memvid, last reviewed 2026-04-05; AI Meets Brain, 2026-04-12) were considered and deferred: S2 requested both row updates, and neither project has a governance or veto model. The Governed Collaborative Memory row (2026-10-25) is current; I read its absorption note, not the paper, so its row is not updated.

**Blind spots found:**
1. **Under-erasure through a citation.** An archive entry would outlive the episodes it summarises. Fixed by D8.
2. **A scan that erases first and fails late** would strand citing entries where no retry finds them (agent and resource scans). Fixed by refusing first (D10).
3. **A citation landing mid-run.** Fixed by the per-episode re-check (E8).
4. **A route test's `MagicMock` runtime** would be passed as the archive and break every route test. Fixed by accepting only a real `ArchiveStore` (E4).
5. **Vetoing an archived source** would have two meanings. Refused (D5).
6. **A veto that an edit evades.** Fixed by keying on the source, not the content (D4).
7. **Reverting a schema bump** would block every reset. Avoided by staying at v1 (D7).
8. **The open `/forget` route.** Registered, not fixed (R1).
9. **An unavailable archive** skips the check. Registered (R2).
10. **The pending set at `--full`** would be destroyed under opt-in review. This is why opt-in review is deferred (D2 B).
11. **The review's own writes.** `initialize()` writes schema statements on open (R7).
12. **A citation cell the read cannot interpret** (an object, a string, a list of non-strings, SQL NULL or empty text) answered "nothing cites this", so an erasure went on (round 1, M1-F1 = M3-F2). Fixed in A2: the read raises (V6b, E5, E8).
13. **A side effect moved before the refusal** passed every test that had no attachment store or audit log (M3-F1). Fixed in A2 by E9 and rows E-6, E-7.
14. **The lock protects rollback isolation, not race outcomes** (M1-F2), so no race test sees it. Fixed in A2 by V7b and rows K24 to K26.
15. **A content-addressed attachment shared by two episodes** is unlinked when either is erased, even when the other is cited (M3-F3). Pre-existing AD-754 behaviour; registered (R11).

## 14. Diff Reviewer: properties to verify

1. `promote_entry` refuses a vetoed source in the same single statement that checks the erasure marker and the key: no window exists between a veto check and the insert. A refused insert is classified erased, then vetoed, then present, and `source_state` evaluates the same three conditions in the same order with the same SQL constants, returning CREATED only when none holds.
2. `veto_source` validates exact types (a plain `str` is not a `SourceKind`), writes through one `INSERT … SELECT … WHERE NOT EXISTS … ON CONFLICT DO NOTHING` under `_write_lock`, and returns RECORDED only when it inserted one row. ARCHIVED, ERASED and ALREADY_VETOED write nothing, and a second veto never changes the first reason. The row holds no title, content, metadata or hash.
3. `archive_vetoes` has a unique index on `(source_kind, source_ref)` created on every open; `user_version` stays 1; an S1-era v1 file keeps every row.
4. `entry_ids_citing` raises (never returns `()`) when the store is closed (RuntimeError), when its argument is not a list or tuple of strings (TypeError), or when any fetched citation cell is not a JSON list of strings (ValueError: malformed JSON, an object, a string, a number, `null`, a list holding a non-string, empty text or SQL NULL; `_CITING_SQL` skips only the canonical `'[]'`). It ignores blank ids, returns ids ascending and runs one statement per call. No read takes `_write_lock`, and no method holding the lock calls another store method. V7b pins the lock and the veto's rollback: a write whose commit fails leaves nothing the next write commits or is decided by.
5. Every AD-754 entry point (`forget_episode`, `forget_resource`, `forget_agent_memory`) checks the open archive before anything is erased: the episodes, their own attachments (BF-868's declared fields) and the audit marking. E9 proves it with a real `FilesystemAttachmentStore` and a real `AuditLog` at each entry point and at the per-episode check. A refusal erases nothing and raises `ArchiveCitationsBlockErasure` carrying only ids. A per-episode re-check inside `_forget_all` turns a late citation, or a cell that becomes unreadable, into a per-episode failure. An attachment blob that another episode also references is unlinked as before S3, even when that episode is cited (register R11). With no archive the behaviour is byte-identical to the base.
6. `/forget` passes the manager only a real `ArchiveStore` (any other value is None) and answers 409 with `archive_entries_cite_erased_episodes` and the ids, logging the count only. No `src` path other than `__main__.py` names `erase_entry` or `veto_source`; `ErasureManager` is built only in `routers/security.py`; `entry_ids_citing` is named only in `knowledge/erasure.py`. A citation read that fails reaches the route as the read's own error, with nothing erased (E5). An empty request is answered 422 by the request model, before the route's 400 (register R14).
7. `probos archive pending` and `probos archive veto` print with plain `print`; they exit 2 for a disabled archive or a bad argument; the veto exits 1 for a source not in the current plan or already archived, and 0 when it records, finds one already vetoed or erased, or the Captain declines. Their `--config` and `--data-dir` use `argparse.SUPPRESS`, so a root option before the command survives.
8. The reset's flow, refusals and exit codes are unchanged; only its promotion message gains the vetoed count, and the dry run gains one line after the withheld list. The `--dry-run` path still opens no archive.
9. `ProbOSRuntime.archive_store` is a read-only property returning `_archive_store`; shutdown's close of `_archive_store` is untouched.
10. The new tests use the real store, records, promotion service, `EpisodicMemory`, manager, attachment store, assistant audit log, app route and CLI. The stand-ins are: the config loader (as in S1); the E8 and E9 subclass, which lands a real promotion (or rewrites one real cell) between two real reads; V7b's connection wrapper, which pauses and fails one commit of a real connection; and the route tests' `MagicMock` runtime (S2a's `_runtime`, in E2 and E4), whose `archive_store` is a writable attribute, not the production property. E7 pins the property itself on `ProbOSRuntime` (read-only, returning `_archive_store`). Every archive lies under `tmp_path`.

## 15. Acceptance criteria

1. A Captain veto stops a promotion and is recorded, content-free, and survives later resets and revisions of the source (V2, V3, V7, V7b, C2; K1 to K9, K24 to K26).
2. The Captain can review what the next promotion would do with each source before a reset, and the review agrees with what the promotion then does (V5, V5b, V9, C1, C7; K11 to K14, P4, P5, C-9).
3. An AD-754 erasure never leaves an archive entry citing an erased episode: it erases nothing (the matched episodes, their own attachments and audit rows) while one cites a match or a citation cannot be read, and once the Captain has erased the entry through the CLI the retry erases the episodes (V6b, E1, E2, E5, E8, E9; K15 to K23, E-1 to E-7, S-1 to S-4).
4. No agent or service path updates or deletes an entry, or records or lifts a veto (V10, C6, E6, and S1's R11 and P15).
5. Promotion before a reset stays on by default and reports vetoed sources (C2, C5; C-5, C-8).
6. Every test in §6 fails on its milestone's base as named, and every row in §10 is killed by the named test. One broad gate and one PR for M1 to M4; cross-family review of M1 and M3 (tier HIGH).
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**R1.** `POST /api/security/forget` has no authorization dependency (`routers/security.py:77-81`; the app's only middleware is CORS), so with a crew-scope token configured any local caller can still erase episodes. AD-1340 S2a recorded this in prose. S3 keeps the route from erasing archive entries (it refuses instead). Adding `require_crew_scope` is a tightening with two consumers to update (the S2a and S2b seam tests post to it without the header); a token-gated archive cascade (D8 C) could follow it.

**R2.** With the Ship's Archive enabled but unavailable (it failed to open at boot, or shutdown has closed it), an AD-754 erasure proceeds without the citation check (`runtime.archive_store` is None). This is inert until S4 produces citations. S4 should decide whether "enabled but unavailable" refuses the erasure instead.

**R3.** A promotion that commits after a per-episode check and before that episode's erase could cite an episode as it is erased. No in-vessel promoter exists until S4 and S5. Those slices should refuse to promote a record citing an episode that is no longer live, or re-check after the erase.

**R4.** A veto cannot be lifted (it is append-only, like the erasure markers). A Captain-only lift that keeps the original row as audit would be a follow-up if a mistaken veto ever needs undoing.

**R5.** The Captain has no list of archive entries by id. `probos archive erase` needs an id, and `pending` shows ids only for sources still in Ship's Records. After a `--full` reset an entry whose source is gone has no lookup surface.

**R6.** No bulk erase: an AD-754 refusal that names N entries needs N `probos archive erase` calls. This is inert until S4.

**R7.** `probos archive pending` and `veto` open the archive through `initialize()`, which runs the schema statements, writes `user_version` and creates a missing file (S1's RA1-3 parity) on the live vessel's file. A read-only open for the review would avoid writes.

**R8.** Not verified: whether the AD-1328 command policy stops an agent's `run_command` from invoking `probos archive veto` or `erase`, the Captain-only CLI (S1's surface too).

**R9.** `generations` has no vetoed count, so a close's counts no longer add up to the plan when a source is vetoed. `archive_vetoes` is the record. Adding a column needs a migration of `generations`.

**R10.** The dry run's "N to promote" counts sources that are vetoed, erased or already archived (S1 behaviour). S3 adds a pointer to `pending` rather than changing S1's line.

**R11.** A content-addressed attachment blob that two episodes reference is unlinked when either is erased: `knowledge/erasure.py:331-339` unlinks each id and checks no other owner (unchanged by S3; the base does the same). With an entry citing episode A only, erasing B (uncited) removes A's attachment: `deleted=['ep-001']`, `live=['ep-000']`, `citations=(1,)`, `attachment_exists=False` on the base and the candidate (round 1, the M3 reviewer's `m3-test_late_failure_and_shared_trace.py` and `m3-test_shared_baseline_comparison.py`). S3's guarantee covers the matched episodes and their own attachments (D10, §14 property 5). The fix changes AD-754's attachment ownership (unlink a blob only when no other live or archived episode references it, or refuse while a cited episode does), so it is a separate follow-up issue on `knowledge/erasure.py`, ordered before S4 makes citing entries normal; S4's premise table names it. A fix that keeps bytes the requester asked to erase, because another episode holds them, weakens an erasure guarantee and is the Captain's decision.

**R12.** Round 1 confirmed by execution (2026-10-26). R2: with no runtime archive an erasure goes through while a persisted citation remains. R3's window is demonstrated, not only argued: a promotion committed after the per-episode check gave HTTP 200 (two 200s for two concurrent requests) while an entry still cited the erased episode. It stays bounded as recorded (only the offline reset promotes, and its records cite none), and checking that an episode is live at promotion time would not close it. R7 holds at byte level: `pending` changes the file's header change counter, and creates a missing file at v1. R8: the default command policy returns `no_policy` and `runs=True` for both `probos archive veto` and `erase`; the whole admission chain is still unverified.

**R13.** The citation check reads every citing row once per call, and a bulk erasure makes N+1 calls (the scan's and one per matched episode). 1,000 matched episodes against 10,000 citing entries took 28.5 s, against 16.4 s with no archive (1,001 reads, 10,010,000 rows fetched, 13.0 s inside the checks; 18.1 s against 10,000 uncited entries). That is tolerable for a deliberate bulk erasure, not for an interactive guard (round 1, `m3-test_cascade_cost.py`). An indexed citation table (episode id to entry id), or one read per erasure, is S4's to schedule before citing entries are produced continuously. A2 keeps the bound: the statement also fetches NULL and empty cells, which canonical files never hold.

**R14.** `POST /api/security/forget` with no target answers 422 from its request model, on the base and the candidate; the route's 400 branch (`routers/security.py:104-108`) is reached only when model validation is bypassed. No client handles the 409: `ui/src/components/wardroom/ForgetThis.tsx` is an unwired callback component (`ForgetThis|onForgetEpisode|forgetEpisode` finds only the component), so the 409's CLI instruction is the Captain's way through today.

**R15.** A revision of an archived source cannot be vetoed while its entry stands: `veto_source` returns ARCHIVED (D5), and the next promotion archives the revision as a second entry (round 1, the M1 reviewer). The Captain's source-wide stop is to erase the entry (S1's marker blocks the source with any content), which also removes the accepted version. A veto that blocks later revisions while keeping the accepted entry is not built.
