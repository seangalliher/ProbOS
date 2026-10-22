# AD-1341 S1: knowledge the crew published is promoted into the Ship's Archive before a reset, with provenance, and the Captain can erase an archive entry

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** M1, M2 and M3 are build-ready. Amendment A1 (2026-10-22, `claude-architect`, from the orchestrator's dry run at `0f13771c`) writes M3 as §7.9 to §7.14 and adds §7.6b and §7.6c to M2 (the config facade baseline and its pinned counts); M4 is §8. Amendment A2 (2026-10-22, `claude-architect`, from M1's round-1 review at `6190fd69` and the whole-contract phantom precheck) serialises the store's writes and its close on its one connection (D16, F1), makes an id beyond SQLite's rowid range no entry (D17, F2), and rewrites one line group each in §7.9 and §7.14 that the precheck flagged (no behaviour change). Slice 1 of 6 of #1569; it does not close the issue. **Tier HIGH** (the archive, an erasure, data integrity). No new AD or BF number. **Base:** `origin/main` `0e122174`, tree `70e8542d8b3b7ae262e91ad147caedfaeb28c9a1`. BF-903 merges first; it touches only `__main__.py`'s pairing CLI and the trackers, so M3 and §8 re-anchor on text. **Source:** the Architect's consults `98e0fdbf` (2026-10-18) and this one.

**Tests:** M1 `tests/test_ad1341_s1_archive_store.py`: 20 functions, 48 cases (A2 adds A14, A14b, A15, A16). M2 `tests/test_ad1341_s1_promotion.py`: 16 functions, 34 cases. Updated where they pinned the old write: `tests/test_ad524_ships_archive.py` (3 tests and its helper, M1). M2 also updates the four pinned facade counts in `tests/test_ad1270e1_config_facade.py` (7.6c). M3 `tests/test_ad1341_s1_reset_and_erase.py`: 15 functions, 24 cases; updated fakes: `tests/test_reset_integration.py` (its helper), `tests/test_distribution.py` (6 call sites), `tests/test_proactive.py` (2), `tests/test_identity_deterministic.py` (3).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

**Mechanical repair by the orchestrator (2026-10-22), no decision changed:** section 8's two tracker pairs are re-anchored on BF-903's head line and its *Reversal* bullet, because BF-903 (merge `80456da2`) landed after this contract was written against `0e122174`, as section 8 itself anticipated.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| The archive's only write is `append`; no production code calls any archive write | present | `archive_store.py:81-119`; the only calls on the store in `src` are `search`, `initialize` and `close` (§11, Absence Verified) |
| The Oracle returns any archive row to any reader | present | `oracle_service.py:1134-1157` |
| `RecordsStore.list_entries` and `read_entry` work without `initialize` | present | `records_store.py:930-1001` use only `_repo_path` and the filesystem |
| Ship's Records survive a tier 2 reset | present | `__main__.py:2648-2655`: only tier 3 lists `ship-records` |
| Tier 2 deletes the ship's instance id | present | `__main__.py:3017-3021` |
| `_cmd_reset` has no running-vessel guard; AD-816's guard exists | present | `__main__.py:2883-3077`; `pidfile_guard.py:109`, `:168` |
| `archive_store` is a baselined undeclared store with `[archive]` | present | `docs/development/store-baseline.yaml:121-123`; `check_store_registry.py:1084-1092` (rule 11) |
| The live archive has 0 rows at `user_version` 0 (orchestrator's probe, 2026-10-22) | taken as given | not run here |
| Only `probos serve` holds the AD-816 pidfile; the interactive shell takes none | present | `__main__.py:745-751`; Absence A1-AV1 |
| Two async tests call `_cmd_reset` inside a running event loop | present | `test_bf902_fts_reconciliation.py:242` (tier 2), `:259` (tier 1), through `test_reset_integration.py:44-57` |
| No caller reads `_cmd_reset`'s return value | present | `__main__.py:3446-3448`; Absence A1-AV2 |
| The config facade pins 307 public names and 294 owned, in its baseline and in four test lines | present | `config-facade-baseline.yaml:54-55, 447`; `test_ad1270e1_config_facade.py:1521, 1522, 1555, 1791`; Absence A1-AV8 |

## 1. Problem

The Ship's Archive (AD-524) is meant to carry knowledge across crew generations. It is empty, and nothing writes it:
- `append` has no production caller.
- `probos reset` promotes nothing before it wipes.
- The archive records no provenance (where an entry came from, its classification, its hash).
- The Captain has no way to erase an archive entry.

At `--full`, everything the crew published in Ship's Records is lost.

## 2. Solution overview

- **M1, the store.** Schema v1, added in place to a v0 archive:
  - provenance columns;
  - a partial unique index on `(source_kind, source_ref, content_sha256)`;
  - a `generations` table and an `archive_erasures` table;
  - `secure_delete` set and verified on every connection.

  `promote_entry(PromotionRecord)` becomes the one write, `append` is removed, and `erase_entry(id, reason)` deletes the row and writes a marker in one transaction. The contract types (`SourceKind` with no episode member, `PromotionRecord`, `GenerationRecord`, `PROMOTABLE_CLASSIFICATIONS`) live in the store module.
- **M2, the service.** `knowledge/archive_promotion.py` is records-only:
  - a fixed criterion per source;
  - an anonymous read;
  - the C1 classification gate;
  - promotion with provenance;
  - no model call, and no swallowed failure.

  It adds one shared records-path resolver.
- **M3, the CLI and the reset (Amendment A1).** At tier 2 and above `probos reset` promotes first and refuses on any failure, before deleting anything. `--skip-promotion REASON` is audited. `--dry-run` lists the plan. Every executing reset holds the AD-816 pidfile. `probos archive erase` is the Captain's erasure.
- **M4.** Trackers.

## 3. Decisions

- **D1 (premises).** §0. The earlier consult's decisions 2.1–2.8 and C1 stand, except as D3 and D4 say.
- **D2 (slicing).** One PR, four milestones: M1 store, M2 service, M3 CLI and reset, M4 trackers. Each milestone is one Builder delegation and one local commit; the review runs per milestone and the broad gate once. M1 can be built and reviewed alone; M2 needs M1; M3 needs both.
- **D3 (the idempotence key, revised from 2.2).**
  - **(A) chosen:** `(source_kind, source_ref, content_sha256)`. The same source with the same content is archived once, under the timeline that first promoted it. A changed document is a new entry under the timeline that changed it.
  - (B) the earlier key, with `timeline_id`: rejected. Its premise was that a reset reads records the ending crew wrote. False: Ship's Records survive tier 2 (§0), so every default reset would re-archive every surviving record under the new timeline. That is false provenance (S2's "generation N" label would be wrong), duplicates, and it undoes an erasure.
  - (C) attribute by the frontmatter's `created` time: rejected. It is self-reported, and Captain's log files are appended to over the day.
- **D4 (the one write).** `promote_entry(record: PromotionRecord) -> PromotionOutcome`.
  - `append` is removed, not made private: nothing in `src` calls it, and the only test caller is updated (7.2).
  - Named `promote_entry`, not `promote`: two other classes already have a `promote` method, so a census by name could not tell them apart.
  - The erasure check and the insert are one `INSERT … SELECT … WHERE NOT EXISTS … ON CONFLICT DO NOTHING` statement. An erasure can never land between a check and the write.
- **D5 (contracts in the lowest layer).** `SourceKind` (closed: convergence report, published report, Captain's log, notebook finding; no episode member), `PromotionOutcome`, `GenerationOutcome`, `PromotionRecord`, `GenerationRecord` and `PROMOTABLE_CLASSIFICATIONS` live in `knowledge/archive_store.py`.
  - The records validate on construction, with exact-type checks so a plain `str` cannot pass as a `SourceKind`.
  - A record narrower than `ship` cannot be built (C1, enforced at the store).
- **D6 (migration).** Additive and idempotent:
  - `_SCHEMA` creates the v0 table and the two new tables (`IF NOT EXISTS`);
  - each v1 column is added only where absent, so a migration that stopped part-way finishes on the next open;
  - then the partial unique index, then `user_version = 1` last.

  `secure_delete=ON` is set and read back, as AD-1340 does (`episode_archive.py:468-472`). A file at any version other than 0 or 1 is refused unopened. At boot that disables the Oracle's archive tier with AD-524's existing warning (`cognitive_services.py:689-695`).
- **D7 (the erasure marker).**
  - **(A) chosen:** the marker holds the entry id, timeline, source kind, source ref, the Captain's reason (1–500 characters) and the time; never the title, content, metadata or hash. `promote_entry` refuses a source a marker names (kind and ref), with any content.
  - (B) no source ref in the marker: rejected. The source still exists in Ship's Records, so the next reset would archive it again and undo the erasure.
  - (C) keep the hash too: rejected. A hash of short content can be guessed, and kind plus ref already blocks.

  Reason codes instead of free text were considered and rejected, for parity with AD-1343's free-text reasons; M3's help text asks the Captain not to restate the content.
- **D8 (criteria, M2).** `source_kind_for(path, frontmatter)`:
  - `reports/convergence/` by `system` (AD-551) is a convergence report;
  - `captains-log/` by `captain` is the Captain's log;
  - any other `reports/` document with status `published` is a published report;
  - `notebooks/` with a non-empty `claim_id` (AD-1140's governed route into the commons) or status `published` is a notebook finding.

  Everything else is never promoted: manuals, duty logs, bills, consultations, creative work, drafts and working notes. The service reads as the anonymous reader (`ARCHIVE_READER = ""`, BF-679). It withholds anything the read refuses, anything whose classification is not `ship`/`fleet` (C1), and any document with an empty body; withheld paths are reported. No model call.
- **D9 (generations).** Each close at tier 2 or above writes one `generations` row: the timeline, tier, outcome (`promoted` or `skipped`), counts and reason. A skip requires the Captain's reason; a promotion requires a timeline. This is the audit for `--skip-promotion` (M3) and the generation order S2 will label.
- **D10 (one resolver).** `config.resolve_records_repo_path(records, data_dir)` sits beside `resolve_archive_db_path`. Startup's default branch calls it (behaviour unchanged); M3's reset reads the same path.
- **D11 (store registry).**
  - **(A) chosen:** update the baselined row to `[archive, archive_erasures, generations]` in M1's commit.
  - (B) declare the store now: rejected for this slice. Its file lives outside `data_dir` (AD-1265's second backup root), and what a declaration means there is a separate decision (register).
- **D12 (running vessel, M3).**
  - **(A) chosen:** every executing `probos reset` (`--soft` included) acquires the AD-816 pidfile after confirmation and releases it when done; a live owner means refuse, exit 1, nothing touched. It protects against a promotion reading records mid-write, deletions racing a live writer (a locked file on Windows leaves a partial reset), and a vessel booting mid-reset and creating a new instance id. `--dry-run` takes no pidfile, following `verify-snapshot`. Only `probos serve` takes the pidfile (`__main__.py:745-751`); the interactive `probos` shell takes none, so a vessel started that way is not seen (register RA1-1). While a reset holds it, `serve` refuses to boot (exit 2) and the `rebuild-episodic` and `backup-reclaim --force` probes refuse.
  - (B) `assert_no_other_instance`: rejected. It only probes, so a vessel could start right after the check.
  - (C) warn: rejected. The command deletes.
- **D13 (archive disabled, M3).** With `archive.enabled` False there is nowhere to promote to. The reset prints a notice and proceeds; this is configuration, not a failure. `probos archive erase` refuses with exit code 2.
- **D14 (tier).** HIGH.
- **D15 (the Captain).** Nothing in S1 requires the Captain; C1 is applied as decided.
- **D16 (one transaction at a time; Amendment A2, F1).** The store's one connection serves every call, and a `ROLLBACK` (`_rollback_quietly`) or a `COMMIT` ends whatever that connection has open. Two overlapping calls could therefore undo each other's work and still report success (M1 round 1, reproduced: two concurrent erasures, one of an existing entry and one of a missing id, returned `[True, False]` with the row kept and no marker).
  - **(A) chosen:** a store-owned `asyncio.Lock`, `_write_lock`, created in `__init__` (AD-1340 R3's pattern, `episode_archive.py:451-455`). `promote_entry`, `record_generation`, `erase_entry` and `close` hold it from the `_db` check through the commit or rollback. `async with` releases it on every exit, cancellation included, and a rollback is queued on the connection before the release, so it runs before any other call's statements. Reads and `initialize` take no lock (AD-1340's rule): a read issues no commit or rollback; it sees the connection's state, a write in flight included (register RA2-1). No store method calls another, so the non-re-entrant lock cannot deadlock (Absence A2-AV1). `close` waits for a write in flight and, as before, clears `_db` only after a successful close, which shutdown's last resort relies on (`test_issue1419_failed_start_rollback.py:2254`).
  - (B) a second connection for writes: rejected. Two writers on the write connection have the same defect, so it would still need (A). It changes nothing in the store registry, backup coverage, the `.db` literals or the census (same file, same tables); it only adds a second `secure_delete` check and a second handle for shutdown.
  - (C) record and ship: rejected. Today every `src` call is awaited alone (Absence A2-AV2), but S2 to S6 add writers inside the running vessel, where an erasure would report success and not happen.
  - (D) a connection per call: rejected; it changes the store's lifecycle and the shutdown handover for no gain over (A).
- **D17 (ids beyond SQLite; Amendment A2, F2).** `erase_entry` returns False, writing nothing, and `entry_by_id` returns None, for an id above `2**63 - 1`, SQLite's largest INTEGER and so its largest rowid; binding a larger int raised `OverflowError`. `entry_by_id` also returns None below 1. M3's CLI reaches `entry_by_id` first with the Captain's id (`argparse` `type=int`; only `<= 0` refused), so an over-large id now prints "No Ship's Archive entry has id …" (exit 1) instead of "The erasure failed: OverflowError: …" (exit 1).

**Disclosed effects.**
1. The live archive migrates to v1 on the first boot after merge (0 rows, additive).
2. An archive at another schema version is refused at boot; the Oracle's archive tier is off, with the existing warning.
3. (M3) `probos reset` at tier 2 or above promotes first and refuses on failure, exiting 1 (it always exited 0 before). `--skip-promotion REASON` is recorded.
4. (M3) Every executing reset refuses while a vessel owns the data directory.
5. Erased bytes stay in earlier AD-1265 snapshots until they age out (as in AD-1340).
6. A record written in one generation but first eligible in a later one is attributed to the later timeline.
7. Two ships sharing the default archive path keep one entry for identical content at the same records path, under whichever ship promoted it first.
8. (M3) With no instance id, records to promote refuse the reset. Two resets with no boot between therefore refuse the second time unless `--skip-promotion REASON` is given, even when everything is already archived (register RA1-2). A data directory with no instance id and nothing to promote resets with no generation row.
9. (M3) `probos reset` creates a missing data directory (the pidfile's directory); `probos archive erase` creates an empty v1 archive when there is none (register RA1-3).
10. (M3) Only `probos serve` holds the pidfile, so the reset does not see a vessel started as the interactive shell (register RA1-1).

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate at `-n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Files (§7) | Focused gate |
|---|---|---|
| **M1** store | 7.1 `knowledge/archive_store.py`; 7.2 `tests/test_ad524_ships_archive.py`; 7.3 `docs/development/store-baseline.yaml`; 7.4 new test | `tests/test_ad1341_s1_archive_store.py tests/test_ad524_ships_archive.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1256_store_registry.py tests/test_ad1265_backup_coverage.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` |
| **M2** service | 7.5 `config.py`; 7.6 `startup/cognitive_services.py`; 7.6b `docs/development/config-facade-baseline.yaml`; 7.6c `tests/test_ad1270e1_config_facade.py`; 7.7 new `knowledge/archive_promotion.py`; 7.8 new test | `tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_archive_store.py tests/test_records_store.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf084_truncation_and_manuals.py tests/test_ad1270e1_config_facade.py tests/test_layer_boundaries.py tests/test_ad1265_backup_coverage.py tests/test_ad1256_store_registry.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check` |
| **M3** CLI and reset | 7.9 `__main__.py`; 7.10 `tests/test_reset_integration.py`; 7.11 `tests/test_distribution.py`; 7.12 `tests/test_proactive.py`; 7.13 `tests/test_identity_deterministic.py`; 7.14 new test | `tests/test_ad1341_s1_reset_and_erase.py tests/test_reset_integration.py tests/test_distribution.py tests/test_proactive.py tests/test_identity_deterministic.py tests/test_ad1340_s1_restore_reset.py tests/test_bf902_fts_reconciliation.py tests/test_bf892_spawn_env_guard.py tests/test_quality_hardening.py tests/test_dotenv.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_archive_store.py tests/test_ad1265_backup_coverage.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M4** trackers | §8 | `tests/test_ad1184_ad_ledger.py`; `scripts/gen_ad_ledger.py --check` |

If a test outside §7 fails only because it called `ArchiveStore.append`, update it to `promote_entry` with an inline `AD-1341 S1 (#1569)` reason; never delete it. Stop and report any other failure.

### M3 specification (written as Amendment A1: §7.9 to §7.14)

**§7.9 to §7.14 are binding. Where they differ from this specification:**
1. `--skip-promotion` is checked in `_cmd_reset` right after the tier, before anything is read, locked or deleted. It exits 2 for a blank or over-long reason and at tier 1.
2. A declined confirmation returns 0.
3. The archive-disabled check comes before the one `asyncio.run`, because `test_bf902_fts_reconciliation.py:242` and `:259` call `_cmd_reset` inside a running loop.
4. With no instance id, the plan is read first and nothing is opened: anything to promote refuses; nothing to promote proceeds with no generation row.
5. The tier loop is re-indented inside the pidfile's `try`, not extracted, so the BF-892 site key `("src/probos/__main__.py", "_cmd_reset")` keeps both git launches.
6. `_cmd_archive` writes with plain `print`, so a title or reason is never markup. It also exits 2 for an id below 1 or a reason outside 1 to 500 characters, and 0 when the Captain declines.
7. The `test_distribution.py` and `test_identity_deterministic.py` fakes gain `.archive` by assignment before the call. Their constructor lines are left out of every block, because the precheck flags the `SimpleNamespace` call. `_run_reset` asserts exit 0.
8. The new test file adds R4b, R10b and R13 (15 functions, 24 cases).
9. There are ten mutation rows, M-R1 to M-R10.

**`src/probos/__main__.py`:**

1. **Parser.**
   - `reset --skip-promotion REASON`: a string, at most 500 characters and non-empty after stripping, otherwise exit 2.
   - A new `archive` subcommand with sub-command `erase ENTRY_ID --reason TEXT [--yes] [--config PATH]`.
   - `main` becomes `sys.exit(_cmd_reset(args))` and gains `if args.command == "archive": sys.exit(_cmd_archive(args))`.
2. **`_cmd_reset(args) -> int`**, in this order:
   1. the deprecated-flag notice;
   2. config, `data_dir` and tier, as today;
   3. the active-task count;
   4. `--dry-run`: when the tier is 2 or above and the archive is enabled, also print `plan_promotion` over `resolve_records_repo_path(config.records, data_dir)`, attributed to `_read_instance_id(data_dir)`. It opens no archive and writes nothing.
   5. confirmation;
   6. `acquire_pidfile(data_dir)` (D12); `AnotherInstanceRunning` prints and returns 1, and the acquired file is unlinked in `finally`;
   7. at tier 2 or above, `_promote_before_reset(...)`; a `False` return prints the reason and returns 1 **before** the tier loop;
   8. the existing tier loop, unchanged;
   9. return 0.

   Tier 1 never reads `config.archive`.
3. **`_read_instance_id(data_dir) -> str`**: `ontology/instance_id`, stripped, or `""`. It is read before any deletion; promotion happens before the tier loop.
4. **`_promote_before_reset`** (sync; one `asyncio.run` of an inner coroutine):
   - archive disabled: print a notice, return True (D13);
   - archive path from `resolve_archive_db_path(config.archive)`, creating the parent only for the computed default, as startup does;
   - records from a `RecordsStore` over the resolved path, never initialised;
   - with `--skip-promotion`: `record_generation(SKIPPED, timeline=<instance id or "">, reason)`;
   - otherwise: an empty instance id with a non-empty plan refuses ("no instance id: provenance cannot be attributed; pass --skip-promotion REASON"); else `promote_ship_records` then `record_generation(PROMOTED, counts)`;
   - any exception: print `TypeName: message`, return False;
   - the store is closed in `finally`.

   Never construct the store as `store = ArchiveStore(...)` and then call a new method on it in a contract block (the precheck's pattern B would flag it); use a helper.
5. **`_cmd_archive(args) -> int`**:
   - archive disabled: 2;
   - `entry_by_id` is None: print "no such entry", return 1;
   - show the entry's title, kind, ref and timeline, and prompt unless `--yes`;
   - `erase_entry`;
   - say that the source still exists in Ship's Records and will not be promoted again;
   - return 0.

**Tests to update** (archive disabled in their fakes):
- `tests/test_reset_integration.py`: in `_run_reset`, add `mock_config.archive.enabled = False`. This also covers `test_ad1340_s1_restore_reset.py` and `test_bf902_fts_reconciliation.py`, which import that helper.
- `tests/test_distribution.py`: the 6 call sites at tier 2 and above, including the dry run. Add `archive=_SimpleNamespace(enabled=False)` and import `SimpleNamespace as _SimpleNamespace` for the precheck.
- `tests/test_proactive.py`: `test_reset_archives_wardroom` and `test_default_reset_preserves_wardroom`.
- `tests/test_identity_deterministic.py`: its 3 call sites.

**New test file `tests/test_ad1341_s1_reset_and_erase.py`**, real `_cmd_reset` on a temporary `data_dir`, a real `SystemConfig` with `archive.db_path` under `tmp_path`, real records:
- R1 a tier-2 reset archives under the planted instance id, then deletes it;
- R2 `--full` archives before `ship-records` is gone;
- R3 a failure exits 1 and deletes nothing;
- R4 `--skip-promotion` writes the generations row;
- R5 `--soft` creates no archive file;
- R6 `--dry-run` lists the plan and writes nothing;
- R7 a live pidfile (`os.getppid()`) refuses at every tier;
- R8 archive disabled;
- R9 no instance id with a non-empty plan refuses;
- R10 the `archive erase` CLI;
- R11 a census: `erase_entry` and `record_generation` are named only in `__main__.py`;
- R12 the chain: a reset, then a later crew's Oracle sees the entry under the old timeline.

**M3 mutation rows:** promote after delete, swallow the error, instance id read after deletion, tier 1 promotes, dry run writes, pidfile guard dropped, skip without its row, a refusal that exits 0.

**M3 focused gate:** the new file plus the 4 updated files, `test_ad1340_s1_restore_reset.py`, `test_bf902_fts_reconciliation.py`, `test_bf892_spawn_env_guard.py`, `test_quality_hardening.py`, `test_ad1265_backup_coverage.py` and the two AD-1343 census files.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `ArchiveStore.append` removed | `tests/test_ad524_ships_archive.py` helper (7.2); no `src` caller | test updated |
| `initialize` migrates, verifies `secure_delete`, refuses another version, and is idempotent on a second call | `startup/cognitive_services.py:686-695` (catches any exception and disables the Oracle tier); every test that opens the store | v0 files keep their rows; v1 files open as before |
| `ArchiveEntry` gains 6 fields, all defaulted | `OracleService._query_archive` (reads only the old fields); `tests/test_ad524_ships_archive.py` `_FakeArchiveStore` (keyword arguments) | none |
| `search`, `get_recent` and `entry_by_id` select 15 columns | the Oracle; the tests; M3's erase prompt | the new fields are filled |
| `promote_entry`, `record_generation`, `erase_entry`, `entry_by_id` | M2's service (`promote_entry`); M3's CLI (the other three) | new |
| (A2, D16) the three writes and `close` hold `_write_lock` through their commit or rollback | M2's `promote_ship_records` and M3's reset and erase, each awaiting one call at a time (Absence A2-AV2); shutdown's close of `_archive_store` (`test_issue1419_failed_start_rollback.py:2254`) | none: no caller overlaps calls on one store, and `close` still clears `_db` only after a successful close |
| (A2, D17) `erase_entry` False and `entry_by_id` None for an id outside 1 to `2**63 - 1` | M3's `probos archive erase` | an over-large id prints "No Ship's Archive entry has id …" instead of "The erasure failed: OverflowError: …"; exit 1 either way |
| `archive.db` schema v1 | the AD-1265 backup root (online backup copies every table); AD-524 code after a revert (its statements name only v0 columns; NULL hashes sit outside the partial index) | additive |
| `store-baseline.yaml` row | `scripts/check_store_registry.py --check`; `tests/test_ad1256_store_registry.py` | row matches the tree |
| `resolve_records_repo_path` | startup's records branch (7.6); M3's reset | the startup branch behaves identically |
| `plan_promotion`, `promote_ship_records`, `source_kind_for`, `ARCHIVE_READER` | M3 | new |
| `config-facade-baseline.yaml` names and counts | `scripts/check_config_facade.py --check`; `tests/test_ad1270e1_config_facade.py` (four pins, 7.6c); the `tests/test_ad1270e2*.py` files that read the baseline | 308 names, 295 owned |
| `_cmd_reset` returns its exit code | `main` (`sys.exit`); no test reads it (Absence A1-AV2); `_run_reset` now asserts 0 | a refusal exits 1, a bad `--skip-promotion` 2 |
| `{data_dir}/probos.pid` held during a reset | `_serve` (refuses to boot, exit 2); the `rebuild-episodic` and `backup-reclaim --force` probes | no vessel boots into a reset |
| `--skip-promotion REASON`, `probos archive erase` | the Captain; `generations` and `archive_erasures` rows | new |

## 6. Tests

The build order: §7.1 opens M1, §7.5 opens M2, Amendment A1's §7.9 opens M3, and §8 is M4.

| Id | Test | Premise asserted | Today |
|---|---|---|---|
| A1 | `test_a_fresh_archive_opens_at_schema_v1_with_its_tables` | `user_version` 1; 6 columns; both tables; a UNIQUE partial index | fails (import) |
| A2 | `test_a_v0_archive_keeps_its_rows_and_is_migrated_in_place[v0, interrupted]` | the live shape migrates; legacy rows are kept with defaults; a second open changes nothing | fails |
| A3 | `test_an_archive_of_another_schema_version_is_refused[later, negative]` | refused unopened; the file is untouched | fails |
| A4 | `test_a_source_and_content_are_archived_once_whatever_the_timeline[same-timeline, next-timeline]` | CREATED, then PRESENT; one row with full provenance (D3) | fails |
| A5 | `test_changed_content_from_the_same_source_is_a_new_entry` | a new hash makes a new row; episode ids round-trip | fails |
| A6 | `test_a_record_the_archive_must_not_hold_is_refused_when_built[10 ids]` | C1, a closed kind, required text, tuple ids, JSON metadata | fails |
| A6b | `test_source_kinds_are_closed_and_none_is_an_episode` | four kinds, none an episode; `{ship, fleet}` | fails |
| A6c | `test_promote_entry_takes_only_a_promotion_record` | TypeError; nothing written | fails |
| A7 | `test_the_store_has_no_append_update_or_delete_and_names_its_writes` | the public surface is exact | fails |
| A8 | `test_erasure_deletes_the_row_and_leaves_only_a_content_free_marker` | one marker row of fixed shape; the erased content and title are absent from the file bytes, while a kept row's bytes are present | fails |
| A9 | `test_an_erased_source_is_not_promoted_again[same-content, changed-content, next-timeline]` | ERASED; nothing written | fails |
| A10 | `test_erasing_an_absent_entry_writes_nothing` | False; no marker | fails |
| A11 | `test_an_erasure_needs_a_reason_and_a_real_id[6 ids]` | ValueError; row intact | fails |
| A12 | `test_a_generation_close_is_recorded` | both outcomes' rows | fails |
| A12b | `test_an_invalid_generation_close_is_refused[6 ids]` | ValueError | fails |
| A13 | `test_the_oracle_reads_a_promoted_entry_across_the_seam` | the real Oracle returns it with its timeline | fails |
| A14 | `test_overlapping_writes_never_report_a_success_another_write_undid[erase-and-missing-erase, missing-erase-and-promote, missing-erase-and-generation]` | D16: what each overlapping call reports is on disk, read back with `sqlite3` | fails on M1 `6190fd69` (the row kept with no marker; no second row; no generation row) |
| A14b | `test_close_waits_for_a_write_in_progress` | D16: `close` never ends a write's transaction | fails on M1 (the erasure raises once its connection is closed under it) |
| A15 | `test_a_failed_write_leaves_an_overlapping_erasure_intact` | D16: a failed write rolls back only itself, and its error reaches its caller | fails on M1 (the erasure is undone and still reports True) |
| A16 | `test_an_id_no_row_can_have_is_no_entry[largest-rowid, above-sqlite, far-above]` | D17: None, then False; nothing written | `[above-sqlite]` and `[far-above]` fail on M1 (`OverflowError`); `[largest-rowid]` is the control and passes |
| P1 | `test_ship_records_read_offline_without_initialize` | premise 2; no `.git` created | fails (import) |
| P2 | `test_each_source_is_promoted_with_its_provenance[5 ids]` | kind, ref, classification, author, content, hash, no episode ids | fails |
| P3 | `test_what_fails_its_criterion_is_not_promoted[8 ids]` | not archived, not withheld | fails |
| P4 | `test_what_is_narrower_than_ship_or_empty_is_withheld_and_the_run_goes_on[4 ids]` | withheld and reported; the rest promoted | fails |
| P5 | `test_a_second_run_archives_nothing_new[same-timeline, next-timeline]` | D3 at the service | fails |
| P6 | `test_an_absent_records_directory_promotes_nothing` | empty report; nothing created | fails |
| P7 | `test_a_source_the_captain_erased_is_reported_and_not_archived_again` | ERASED reported | fails |
| P8 | `test_a_failed_write_propagates` | no swallow | fails |
| P8b | `test_records_to_promote_need_a_timeline` | ValueError | fails |
| P9 | `test_planning_reads_ship_records_and_writes_nothing` | the dry-run basis | fails |
| P10 | `test_a_document_without_mapping_frontmatter_is_never_a_source[3 ids]` | robust to bad frontmatter | fails |
| P11 | `test_a_promoted_record_reaches_a_later_crews_oracle` | records → service → store → Oracle on a reopened file | fails |
| P12 | `test_the_records_path_has_one_resolver[default, override]` | D10 | fails |
| P13 | `test_startup_reads_the_records_path_through_the_shared_resolver` | structural: one call, no second literal | fails |
| P14 | `test_the_service_imports_only_the_knowledge_layer` | layer | fails |
| P15 | `test_only_the_promotion_service_writes_the_archive` | census of `promote_entry` in `src` | fails |
| R1 | `test_a_tier2_reset_archives_under_the_ship_it_closes_then_deletes_its_instance_id` | entries and a `promoted` row under the planted instance id; then tier 2 ran; the pidfile released | fails (no archive; returns None) |
| R2 | `test_a_full_reset_archives_before_ship_records_are_wiped` | archived at tier 3 though Ship's Records are gone after | fails |
| R3 | `test_a_failed_promotion_refuses_the_reset_and_deletes_nothing` | an archive at version 7: exit 1; every file and the instance id kept | fails (deletes) |
| R4 | `test_skip_promotion_records_the_generation_and_archives_nothing` | one `skipped` row with the stripped reason | fails |
| R4b | `test_a_skip_without_a_usable_reason_exits_2_and_touches_nothing[blank, too-long, soft]` | exit 2 before anything is touched | fails |
| R5 | `test_a_soft_reset_never_opens_the_archive` | tier 1 creates no archive file | fails (returns None) |
| R6 | `test_a_dry_run_lists_the_plan_and_writes_nothing` | plan printed; no archive file; a live pidfile is ignored | fails |
| R7 | `test_a_live_vessel_refuses_every_executing_reset[soft, default, full]` | exit 1; nothing deleted; the owner's pidfile kept | fails (deletes) |
| R8 | `test_with_the_archive_disabled_the_reset_proceeds_and_erase_exits_2` | D13 | fails (no `_cmd_archive`) |
| R9 | `test_without_an_instance_id_records_to_promote_refuse_the_reset[with-records, nothing-to-promote]` | refuse; or proceed with nothing opened | fails |
| R10 | `test_the_captain_erases_an_entry_and_the_next_reset_does_not_bring_it_back` | the chain erase → next generation's reset: ERASED, not re-archived | fails |
| R10b | `test_an_erasure_that_cannot_or_should_not_happen_erases_nothing[no-such-entry, zero-id, blank-reason, declined]` | exit 1, 2, 2, 0; nothing erased | fails |
| R11 | `test_only_the_cli_erases_an_entry_or_closes_a_generation` | census: `erase_entry`, `record_generation` named in `src` only by `__main__.py` | fails (named nowhere) |
| R12 | `test_a_later_crews_oracle_reads_what_the_reset_archived_under_the_old_timeline` | reset → archive → a later crew's real Oracle | fails |
| R13 | `test_main_parses_the_new_arguments_and_exits_with_the_command_code[reset, archive-erase]` | the parser and `sys.exit(_cmd_*(args))` | fails (argparse exit 2) |

Updated pins, not new cases: 7.2 (M1); 7.6c (M2); 7.10 to 7.13 (M3).

## 7. The contract

### 7.1 `src/probos/knowledge/archive_store.py` (M1)

Pair 1 of 8: the module docstring and imports.

SEARCH:
```python
"""Ship's Archive — cross-reset generational knowledge persistence (AD-524).

Stores curated knowledge entries that survive resets. Entries are append-only
(no updates, no deletes). Each entry records which timeline (instance) it
came from and when it was archived.

Storage location: {archive_dir}/archive.db (outside instance data_dir).
Default archive_dir: platform-specific ProbOS home / archive/.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)
```
REPLACE:
```python
"""Ship's Archive — cross-reset generational knowledge persistence (AD-524, AD-1341).

Stores curated knowledge entries that survive resets. Agents and services never
update or delete an entry. The one write is ``ArchiveStore.promote_entry``
(AD-1341), called only by the promotion service
(``probos.knowledge.archive_promotion``); it is idempotent on the source and its
content. The one removal is the Captain's ``erase_entry``, reached only from the
offline ``probos archive erase``: it deletes the row and leaves a marker in
``archive_erasures`` that holds no title, content or hash.

Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.

Schema: ``PRAGMA user_version`` 1. A version-0 archive (AD-524) is migrated in
place by adding columns; any other version is refused. Every connection sets
``PRAGMA secure_delete=ON`` and verifies it, so an erased row's bytes are
overwritten in the file (earlier backup snapshots hold them until they age out).

Storage location: {archive_dir}/archive.db (outside instance data_dir).
Default archive_dir: platform-specific ProbOS home / archive/.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)
```

Pair 2 of 8: the entry's provenance fields and the contract types.

SEARCH:
```python
    archived_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


_SCHEMA = """
```
REPLACE:
```python
    archived_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # AD-1341: provenance. Empty for an AD-524 entry written before schema v1.
    source_kind: str = ""
    source_ref: str = ""
    content_sha256: str = ""
    classification: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()


#: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
ARCHIVE_SCHEMA_VERSION = 1

#: AD-1341 C1: the classifications the archive accepts. A later crew reads every entry (the Oracle's archive
#: tier has no reader filter), so nothing narrower than ``ship`` is ever archived.
PROMOTABLE_CLASSIFICATIONS = frozenset({"ship", "fleet"})

#: AD-1341: the longest reason an erasure or a skipped promotion records.
ARCHIVE_REASON_MAX_CHARS = 500


class SourceKind(StrEnum):
    """AD-1341: where a promoted entry came from.

    Closed, and with no episode member: episodes are memory, governed by AD-1340, and are never archived.
    """

    CONVERGENCE_REPORT = "convergence_report"
    PUBLISHED_REPORT = "published_report"
    CAPTAINS_LOG = "captains_log"
    NOTEBOOK_FINDING = "notebook_finding"


class PromotionOutcome(StrEnum):
    """AD-1341: what ``promote_entry`` did with one record."""

    CREATED = "created"
    PRESENT = "present"  # this source with this content is already archived
    ERASED = "erased"  # the Captain erased this source; it is not archived again


class GenerationOutcome(StrEnum):
    """AD-1341: how a crew generation's close was handled at a reset of tier 2 or above."""

    PROMOTED = "promoted"
    SKIPPED = "skipped"


def _required_text(value: object, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"AD-1341: {name} must be a non-empty string")


@dataclass(frozen=True)
class PromotionRecord:
    """AD-1341: one entry to promote, with its provenance.

    Validated when built, so a record the archive must not hold (narrower than ``ship``, an unknown source
    kind, nothing to archive) never reaches the store.
    """

    timeline_id: str
    source_kind: SourceKind
    source_ref: str
    title: str
    content: str
    classification: str
    author_callsign: str = ""
    author_agent_type: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.source_kind) is not SourceKind:
            raise ValueError("AD-1341: source_kind must be a SourceKind")
        for name in ("timeline_id", "source_ref", "title", "content"):
            _required_text(getattr(self, name), name)
        if type(self.classification) is not str or self.classification not in PROMOTABLE_CLASSIFICATIONS:
            raise ValueError(f"AD-1341: only {sorted(PROMOTABLE_CLASSIFICATIONS)} may be archived")
        for name in ("author_callsign", "author_agent_type", "author_did"):
            if type(getattr(self, name)) is not str:
                raise ValueError(f"AD-1341: {name} must be a string")
        if type(self.source_episode_ids) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.source_episode_ids
        ):
            raise ValueError("AD-1341: source_episode_ids must be a tuple of episode ids")
        if type(self.metadata) is not dict:
            raise ValueError("AD-1341: metadata must be a dict")
        try:
            json.dumps(self.metadata)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"AD-1341: metadata must serialise to JSON: {exc}") from exc

    @property
    def content_sha256(self) -> str:
        """The SHA-256 of the content: part of the idempotence key."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GenerationRecord:
    """AD-1341: one crew generation's close at a reset of tier 2 or above, for ``generations``."""

    timeline_id: str
    reset_tier: int
    outcome: GenerationOutcome
    created: int = 0
    present: int = 0
    erased: int = 0
    withheld: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        if type(self.outcome) is not GenerationOutcome:
            raise ValueError("AD-1341: outcome must be a GenerationOutcome")
        if type(self.reset_tier) is not int or self.reset_tier not in (2, 3):
            raise ValueError("AD-1341: a generation closes at a reset of tier 2 or 3")
        if type(self.timeline_id) is not str or type(self.reason) is not str:
            raise ValueError("AD-1341: timeline_id and reason must be strings")
        if len(self.reason) > ARCHIVE_REASON_MAX_CHARS:
            raise ValueError(f"AD-1341: a reason is at most {ARCHIVE_REASON_MAX_CHARS} characters")
        for count in (self.created, self.present, self.erased, self.withheld):
            if type(count) is not int or count < 0:
                raise ValueError("AD-1341: counts are non-negative integers")
        if self.outcome is GenerationOutcome.PROMOTED and not self.timeline_id.strip():
            raise ValueError("AD-1341: a promotion is attributed to the timeline it closes")
        if self.outcome is GenerationOutcome.SKIPPED and not self.reason.strip():
            raise ValueError("AD-1341: a skipped promotion needs the Captain's reason")


_SCHEMA = """
```

Pair 3 of 8: the new tables, the v1 columns and the statements.

SEARCH:
```python
CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);
"""
```
REPLACE:
```python
CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);

CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    reset_tier INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    created_count INTEGER NOT NULL DEFAULT 0,
    present_count INTEGER NOT NULL DEFAULT 0,
    erased_count INTEGER NOT NULL DEFAULT 0,
    withheld_count INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    recorded_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generations_timeline ON generations(timeline_id);

CREATE TABLE IF NOT EXISTS archive_erasures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    timeline_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    erased_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_erasures_source ON archive_erasures(source_kind, source_ref);
"""

# AD-1341 schema v1: the provenance columns, each added to a v0 table only where absent, so a migration that
# stopped part-way finishes on the next open.
_V1_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source_kind", "TEXT NOT NULL DEFAULT ''"),
    ("source_ref", "TEXT NOT NULL DEFAULT ''"),
    ("content_sha256", "TEXT"),
    ("classification", "TEXT NOT NULL DEFAULT ''"),
    ("author_did", "TEXT NOT NULL DEFAULT ''"),
    ("source_episode_ids", "TEXT NOT NULL DEFAULT '[]'"),
)

# AD-1341: the idempotence key. A source with the same content is archived once, whichever timeline promotes
# it: Ship's Records survive a tier 2 reset, so the next reset reads the same documents again.
_PROMOTION_KEY = "source_kind, source_ref, content_sha256"

# Partial: an AD-524 entry has no hash (NULL) and stays outside the key.
_PROMOTION_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_promotion_key "
    f"ON archive ({_PROMOTION_KEY}) WHERE content_sha256 IS NOT NULL"
)

_ENTRY_COLUMNS = (
    "id, timeline_id, category, title, content, author_agent_type, author_callsign, archived_at, metadata, "
    "source_kind, source_ref, content_sha256, classification, author_did, source_episode_ids"
)

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

# The marker copies only the entry's id, timeline and source from the row it is about to delete.
_ERASURE_MARKER_SQL = (
    "INSERT INTO archive_erasures (entry_id, timeline_id, source_kind, source_ref, reason, erased_at) "
    "SELECT id, timeline_id, source_kind, source_ref, ?, ? FROM archive WHERE id = ?"
)

_GENERATION_SQL = (
    "INSERT INTO generations (timeline_id, reset_tier, outcome, created_count, present_count, erased_count, "
    "withheld_count, reason, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# AD-1341 A2 (F2): SQLite's largest INTEGER, so its largest rowid. No row can have a larger id, and binding
# one raises OverflowError, so the lookup and the erasure treat it as a missing id.
_SQLITE_MAX_ROWID = 2**63 - 1


def _valid_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        raise ValueError(f"AD-1341: a reason of 1..{ARCHIVE_REASON_MAX_CHARS} characters is required")
    return reason.strip()


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it (the AD-1213 pattern)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1341: rollback after a failed archive write found no open transaction")


async def _close_quietly(db: Any) -> None:
    """Close a connection whose open failed; the open's own failure is the one reported."""
    try:
        await db.close()
    except Exception:  # noqa: BLE001 -- see the docstring
        logger.debug("AD-1341: closing the archive after a failed open also failed", exc_info=True)
```

Pair 4 of 8: the class docstring, `__init__`'s write lock, `initialize`, and `close` under the lock (Amendment A2, D16).

SEARCH:
```python
class ArchiveStore:
    """Append-only cross-reset knowledge store (AD-524).

    Uses ConnectionFactory protocol for cloud-ready storage.
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None

    async def initialize(self) -> None:
        """Open database and create schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-524: ArchiveStore initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
```
REPLACE:
```python
class ArchiveStore:
    """The Ship's Archive (AD-524), with AD-1341's provenance, promotion and the Captain's erasure.

    Agents and services never update or delete an entry: ``promote_entry`` is the one write and
    ``erase_entry`` the one removal (Captain-only, through ``probos archive erase``). Uses the
    ConnectionFactory protocol for cloud-ready storage.

    AD-1341 A2 (F1): one connection serves every call, and a ROLLBACK or COMMIT ends whatever that connection
    has open. So the three writes and ``close`` hold ``_write_lock`` from their first statement through the
    commit or rollback that ends it, and no call can undo, or land, another call's work (AD-1340 R3's pattern,
    ``episode_archive.py``). Reads and ``initialize`` take no lock: a read issues no commit or rollback, and it
    sees the connection's state, a write in flight included. No method holding the lock calls another store
    method (the lock is not re-entrant).
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None
        self._write_lock = asyncio.Lock()  # AD-1341 A2 (F1): one transaction at a time on the one connection

    async def initialize(self) -> None:
        """Open the database, enable and verify ``secure_delete``, and bring the schema to v1 (AD-1341).

        Additive and idempotent: a v0 archive keeps every row and gains the provenance columns, the partial
        unique index, ``generations`` and ``archive_erasures``. Each column is added only where absent, so a
        migration that stopped part-way finishes here, and ``user_version`` is written last. A file of any
        other schema version is refused, unopened.
        """
        if self._db is not None:
            return
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA secure_delete=ON")
            cursor = await db.execute("PRAGMA secure_delete")
            row = await cursor.fetchone()
            if not row or int(row[0]) != 1:
                raise RuntimeError("AD-1341: secure_delete is unavailable, so an erasure could not be honoured")
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = int(row[0]) if row else 0
            if version not in (0, ARCHIVE_SCHEMA_VERSION):
                raise RuntimeError(
                    f"AD-1341: archive schema version {version} is not one this ProbOS reads "
                    f"(0 or {ARCHIVE_SCHEMA_VERSION}); refusing to open it"
                )
            await db.executescript(_SCHEMA)
            cursor = await db.execute("PRAGMA table_info(archive)")
            present = {column[1] for column in await cursor.fetchall()}
            for name, declaration in _V1_COLUMNS:
                if name not in present:
                    await db.execute(f"ALTER TABLE archive ADD COLUMN {name} {declaration}")
            await db.execute(_PROMOTION_INDEX)
            await db.execute(f"PRAGMA user_version = {ARCHIVE_SCHEMA_VERSION}")
            await db.commit()
        except BaseException:  # close on every exit, cancellation included, then re-raise
            await _close_quietly(db)
            raise
        self._db = db
        logger.info("AD-524: ArchiveStore initialized at %s (schema v%d)", self._db_path, ARCHIVE_SCHEMA_VERSION)

    async def close(self) -> None:
        """Close the connection once no write is in flight (AD-1341 A2, F1). A failed close keeps ``_db``."""
        async with self._write_lock:  # AD-1341 F1: never close inside another call's transaction
            if self._db:
                await self._db.close()
                self._db = None
```

Pair 5 of 8: `append` is replaced by the one write, the generation record, the erasure and a lookup by id.

SEARCH:
```python
    async def append(
        self,
        *,
        timeline_id: str,
        category: str,
        title: str,
        content: str,
        author_agent_type: str = "",
        author_callsign: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Append an entry to the archive. Returns the entry ID.

        This is the ONLY write operation. No updates, no deletes.
        """
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")

        now = time.time()
        meta_json = json.dumps(metadata or {})

        cursor = await self._db.execute(
            """INSERT INTO archive
               (timeline_id, category, title, content, author_agent_type,
                author_callsign, archived_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timeline_id,
                category,
                title,
                content,
                author_agent_type,
                author_callsign,
                now,
                meta_json,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid
```
REPLACE:
```python
    async def promote_entry(self, record: PromotionRecord) -> PromotionOutcome:
        """AD-1341: the archive's one write, called only by ``probos.knowledge.archive_promotion``.

        Idempotent on ``(source_kind, source_ref, content_sha256)``: the same source with the same content is
        archived once, whichever timeline promotes it (PRESENT). A source the Captain erased is not written
        again, with any content (ERASED); the check and the insert are one statement. Any database failure
        rolls the transaction back and propagates: the caller decides what a failed promotion means.
        """
        if type(record) is not PromotionRecord:
            raise TypeError("AD-1341: promote_entry takes a PromotionRecord")
        kind = record.source_kind.value
        params = (
            record.timeline_id, kind, record.title, record.content, record.author_agent_type,
            record.author_callsign, time.time(), json.dumps(record.metadata), kind, record.source_ref,
            record.content_sha256, record.classification, record.author_did,
            json.dumps(list(record.source_episode_ids)), kind, record.source_ref,
        )
        async with self._write_lock:  # AD-1341 F1: the insert and its erasure check commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_PROMOTE_SQL, params)
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

    async def record_generation(self, closure: GenerationRecord) -> int:
        """AD-1341: record a crew generation's close (a promotion run, or a skip and its reason). Returns its id."""
        if type(closure) is not GenerationRecord:
            raise TypeError("AD-1341: record_generation takes a GenerationRecord")
        params = (
            closure.timeline_id, closure.reset_tier, closure.outcome.value, closure.created, closure.present,
            closure.erased, closure.withheld, closure.reason.strip(), time.time(),
        )
        async with self._write_lock:  # AD-1341 F1: the generation row commits or rolls back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_GENERATION_SQL, params)
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        return cursor.lastrowid

    async def erase_entry(self, entry_id: int, reason: str) -> bool:
        """AD-1341: the Captain's erasure (AD-754 extended to the archive), reached only from ``probos archive erase``.

        One transaction: a marker in ``archive_erasures`` (the entry's id, timeline, source kind and source ref,
        the reason and the time; never its title, content, metadata or hash), then the row's delete.
        ``secure_delete`` overwrites the freed bytes. The marker also keeps the source from being promoted
        again. Returns False, writing nothing, when no entry has this id, including an id above SQLite's largest
        rowid (A2, F2). The marker, the delete and the commit or rollback hold ``_write_lock`` (A2, F1).
        """
        if type(entry_id) is not int or entry_id <= 0:
            raise ValueError("AD-1341: an archive entry id is a positive integer")
        text = _valid_reason(reason)
        async with self._write_lock:  # AD-1341 F1: the marker and the delete commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            if entry_id > _SQLITE_MAX_ROWID:  # AD-1341 F2: no row has it, and SQLite cannot bind it
                return False
            try:
                cursor = await self._db.execute(_ERASURE_MARKER_SQL, (text, time.time(), entry_id))
                if cursor.rowcount != 1:
                    await _rollback_quietly(self._db)
                    return False
                await self._db.execute("DELETE FROM archive WHERE id = ?", (entry_id,))
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        logger.warning("AD-1341: the Captain erased Ship's Archive entry %d", entry_id)
        return True

    async def entry_by_id(self, entry_id: int) -> ArchiveEntry | None:
        """AD-1341: one entry, so the erasure can show the Captain what it is about to remove.

        None for an id no row can have: below 1, or above SQLite's largest rowid, which cannot be bound (A2, F2).
        """
        if not self._db or not 0 < entry_id <= _SQLITE_MAX_ROWID:  # AD-1341 F2: ids are positive rowids
            return None
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        return self._row_to_entry(row) if row else None
```

Pair 6 of 8: `search` selects every column.

SEARCH:
```python
        sql = f"""SELECT id, timeline_id, category, title, content,
                         author_agent_type, author_callsign, archived_at, metadata
                  FROM archive
```
REPLACE:
```python
        sql = f"""SELECT {_ENTRY_COLUMNS}
                  FROM archive
```

Pair 7 of 8: `get_recent` selects every column.

SEARCH:
```python
        cursor = await self._db.execute(
            """SELECT id, timeline_id, category, title, content,
                     author_agent_type, author_callsign, archived_at, metadata
              FROM archive ORDER BY archived_at DESC LIMIT ?""",
            (limit,),
        )
```
REPLACE:
```python
        cursor = await self._db.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM archive ORDER BY archived_at DESC LIMIT ?",
            (limit,),
        )
```

Pair 8 of 8: `_row_to_entry` fills the provenance fields (keyword arguments added in the middle of the call).

SEARCH:
```python
            metadata=json.loads(row[8]) if row[8] else {},
        )
```
REPLACE:
```python
            metadata=json.loads(row[8]) if row[8] else {},
            source_kind=row[9],
            source_ref=row[10],
            content_sha256=row[11] or "",
            classification=row[12],
            author_did=row[13],
            source_episode_ids=tuple(json.loads(row[14])) if row[14] else (),
        )
```

### 7.2 `tests/test_ad524_ships_archive.py` (M1: the tests pinned `append`)

Pair 1 of 5.

SEARCH:
```python
from probos.knowledge.archive_store import ArchiveEntry, ArchiveStore
```
REPLACE:
```python
from probos.knowledge.archive_store import ArchiveEntry, ArchiveStore, PromotionOutcome, PromotionRecord, SourceKind
```

Pair 2 of 5.

SEARCH:
```python
@pytest.mark.asyncio
async def test_archive_store_append(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        entry_id = await _append_entry(store, title="Exit note", content="Keep logs")
        assert entry_id > 0
    finally:
        await store.close()


def test_archive_store_append_only() -> None:
    assert not hasattr(ArchiveStore, "update")
    assert not hasattr(ArchiveStore, "delete")
```
REPLACE:
```python
# AD-1341 S1 (#1569): ``append`` is gone and ``promote_entry`` is the archive's one write. This test asserted that
# the old write returned an id; it now asserts that the one write archives a record.
@pytest.mark.asyncio
async def test_archive_store_promote(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        outcome = await _append_entry(store, title="Exit note", content="Keep logs")
        assert outcome is PromotionOutcome.CREATED
        assert await store.count() == 1
    finally:
        await store.close()


def test_archive_store_append_only() -> None:
    # AD-1341 S1 (#1569): no update, delete or append. The one removal is the Captain's ``erase_entry``, reached
    # only from ``probos archive erase``; tests/test_ad1341_s1_archive_store.py holds its marker contract.
    assert not hasattr(ArchiveStore, "update")
    assert not hasattr(ArchiveStore, "delete")
    assert not hasattr(ArchiveStore, "append")
```

Pair 3 of 5.

SEARCH:
```python
        await _append_entry(
            store,
            category="lesson_learned",
            title="Warp",
            content="Shared keyword",
        )
        await _append_entry(
            store,
            category="procedure",
            title="Procedure",
            content="Shared keyword",
        )

        results = await store.search("Shared", category="procedure")

        assert len(results) == 1
        assert results[0].category == "procedure"
```
REPLACE:
```python
        # AD-1341 S1 (#1569): an entry's category is now its source kind; the filter is unchanged.
        await _append_entry(
            store,
            source_kind=SourceKind.CONVERGENCE_REPORT,
            title="Warp",
            content="Shared keyword",
        )
        await _append_entry(
            store,
            source_kind=SourceKind.CAPTAINS_LOG,
            title="Procedure",
            content="Shared keyword",
        )

        results = await store.search("Shared", category="captains_log")

        assert len(results) == 1
        assert results[0].category == "captains_log"
```

Pair 4 of 5.

SEARCH:
```python
            category="exit_note",
            title="Reset lesson",
```
REPLACE:
```python
            source_kind=SourceKind.NOTEBOOK_FINDING,  # AD-1341 S1 (#1569): the category is the source kind
            title="Reset lesson",
```

Pair 5 of 5.

SEARCH:
```python
async def _append_entry(
    store: ArchiveStore,
    *,
    timeline_id: str = "timeline-1",
    category: str = "duty_report",
    title: str,
    content: str,
    author_agent_type: str = "medical",
    author_callsign: str = "Chapel",
) -> int:
    return await store.append(
        timeline_id=timeline_id,
        category=category,
        title=title,
        content=content,
        author_agent_type=author_agent_type,
        author_callsign=author_callsign,
        metadata={"source": "test"},
    )
```
REPLACE:
```python
async def _append_entry(
    store: ArchiveStore,
    *,
    timeline_id: str = "timeline-1",
    source_kind: SourceKind = SourceKind.NOTEBOOK_FINDING,
    title: str,
    content: str,
    author_agent_type: str = "medical",
    author_callsign: str = "Chapel",
) -> PromotionOutcome:
    # AD-1341 S1 (#1569): ``append`` is gone; ``promote_entry`` is the archive's one write. The helper keeps its
    # name so the tests above read as before; each entry is a ship-classified record with its own source ref.
    return await store.promote_entry(
        PromotionRecord(
            timeline_id=timeline_id,
            source_kind=source_kind,
            source_ref=f"notebooks/{author_callsign}/{title}.md",
            title=title,
            content=content,
            classification="ship",
            author_callsign=author_callsign,
            author_agent_type=author_agent_type,
            metadata={"source": "test"},
        )
    )
```

### 7.3 `docs/development/store-baseline.yaml` (M1: rule 11 pins the table set)

SEARCH:
```yaml
- module: probos.knowledge.archive_store
  tables:
  - archive
- module: probos.knowledge.edges
```
REPLACE:
```yaml
- module: probos.knowledge.archive_store
  tables:
  - archive
  - archive_erasures
  - generations
- module: probos.knowledge.edges
```
Verify with `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check`. Do not run `--update-baseline`, which rewrites the whole file.

### 7.4 New file: `tests/test_ad1341_s1_archive_store.py` (M1)

```python
"""AD-1341 S1 M1 (#1569): the Ship's Archive's schema v1, its one write and the Captain's erasure.

Every test runs the real ``ArchiveStore`` through the startup's ``default_factory`` on a temporary file and
reads the file back with ``sqlite3``, so what is asserted is what is on disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.knowledge.archive_store import (
    ARCHIVE_REASON_MAX_CHARS,
    ARCHIVE_SCHEMA_VERSION,
    PROMOTABLE_CLASSIFICATIONS,
    ArchiveStore,
    GenerationOutcome,
    GenerationRecord,
    PromotionOutcome,
    PromotionRecord,
    SourceKind,
)
from probos.storage.sqlite_factory import default_factory

# The AD-524 schema exactly as it shipped, before AD-1341: the shape of the live vessel's file.
_V0_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_agent_type TEXT NOT NULL DEFAULT '',
    author_callsign TEXT NOT NULL DEFAULT '',
    archived_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);
"""
_V1_COLUMNS = ("source_kind", "source_ref", "content_sha256", "classification", "author_did", "source_episode_ids")


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _record(**overrides: Any) -> PromotionRecord:
    fields: dict[str, Any] = {
        "timeline_id": "timeline-one",
        "source_kind": SourceKind.CONVERGENCE_REPORT,
        "source_ref": "reports/convergence/convergence-20261022-000000.md",
        "title": "convergence-20261022-000000",
        "content": "## Convergence Report\n\nThree officers independently traced the coolant drift.",
        "classification": "ship",
        "author_callsign": "system",
    }
    fields.update(overrides)
    return PromotionRecord(**fields)


def _plant_v0(path: Path, *, extra_column: bool = False) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_V0_SCHEMA)
        for title in ("Legacy one", "Legacy two"):
            connection.execute(
                "INSERT INTO archive (timeline_id, category, title, content, archived_at) VALUES (?, ?, ?, ?, ?)",
                ("timeline-zero", "lesson_learned", title, f"{title} content", 1.0),
            )
        if extra_column:  # a migration that stopped after its first column
            connection.execute("ALTER TABLE archive ADD COLUMN source_kind TEXT NOT NULL DEFAULT ''")
        connection.commit()
    finally:
        connection.close()


# --- A1 to A3: the schema -------------------------------------------------------------------------------------


async def test_a_fresh_archive_opens_at_schema_v1_with_its_tables(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.count() == 0
    finally:
        await store.close()
    path = tmp_path / "archive.db"
    assert ARCHIVE_SCHEMA_VERSION == 1
    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert set(_V1_COLUMNS) <= {row[1] for row in _rows(path, "PRAGMA table_info(archive)")}
    tables = {row[0] for row in _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"archive", "generations", "archive_erasures"} <= tables
    index = _rows(path, "SELECT sql FROM sqlite_master WHERE name = 'idx_archive_promotion_key'")
    assert len(index) == 1
    assert "UNIQUE" in index[0][0] and "WHERE content_sha256 IS NOT NULL" in index[0][0]


@pytest.mark.parametrize("interrupted", [False, True], ids=["v0", "interrupted"])
async def test_a_v0_archive_keeps_its_rows_and_is_migrated_in_place(tmp_path: Path, interrupted: bool) -> None:
    path = tmp_path / "archive.db"
    _plant_v0(path, extra_column=interrupted)
    assert _rows(path, "PRAGMA user_version") == [(0,)]  # premise: the live vessel's archive is v0
    for _ in range(2):  # the second open finds v1 and changes nothing
        store = _store(tmp_path)
        await store.initialize()
        try:
            legacy = await store.search("Legacy")
        finally:
            await store.close()
        assert sorted(entry.title for entry in legacy) == ["Legacy one", "Legacy two"]
        assert all(entry.source_kind == "" and entry.content_sha256 == "" for entry in legacy)
    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert _rows(path, "SELECT content_sha256, classification, author_did, source_episode_ids FROM archive") == [
        (None, "", "", "[]"),
        (None, "", "", "[]"),
    ]


@pytest.mark.parametrize("version", [2, -1], ids=["later", "negative"])
async def test_an_archive_of_another_schema_version_is_refused(tmp_path: Path, version: int) -> None:
    path = tmp_path / "archive.db"
    _plant_v0(path)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    finally:
        connection.close()
    store = _store(tmp_path)
    with pytest.raises(RuntimeError, match="schema version"):
        await store.initialize()
    assert await store.entry_by_id(1) is None  # nothing was opened
    assert _rows(path, "PRAGMA user_version") == [(version,)]
    assert "source_kind" not in {row[1] for row in _rows(path, "PRAGMA table_info(archive)")}


# --- A4 to A7: the one write ----------------------------------------------------------------------------------


@pytest.mark.parametrize("second_timeline", ["timeline-one", "timeline-two"], ids=["same-timeline", "next-timeline"])
async def test_a_source_and_content_are_archived_once_whatever_the_timeline(
    tmp_path: Path, second_timeline: str,
) -> None:
    first = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(first) is PromotionOutcome.CREATED
        assert await store.promote_entry(_record(timeline_id=second_timeline)) is PromotionOutcome.PRESENT
        entry = (await store.get_recent())[0]
    finally:
        await store.close()
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT timeline_id, category, title, content, author_callsign, source_kind, source_ref, content_sha256, "
        "classification, author_did, source_episode_ids FROM archive",
    )
    assert rows == [(
        "timeline-one", "convergence_report", first.title, first.content, "system", "convergence_report",
        first.source_ref, hashlib.sha256(first.content.encode("utf-8")).hexdigest(), "ship", "", "[]",
    )]
    assert (entry.source_kind, entry.source_ref, entry.content_sha256, entry.classification) == (
        "convergence_report", first.source_ref, first.content_sha256, "ship",
    )
    assert entry.source_episode_ids == ()


async def test_changed_content_from_the_same_source_is_a_new_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(_record()) is PromotionOutcome.CREATED
        revised = _record(content="## Convergence Report\n\nRevised after review.", source_episode_ids=("ep-1",))
        assert await store.promote_entry(revised) is PromotionOutcome.CREATED
        found = await store.search("Revised after review")
    finally:
        await store.close()
    assert len(_rows(tmp_path / "archive.db", "SELECT id FROM archive")) == 2
    assert [entry.source_episode_ids for entry in found] == [("ep-1",)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"classification": "private"},
        {"classification": "department"},
        {"classification": "secret"},
        {"source_kind": "convergence_report"},
        {"source_ref": "  "},
        {"content": ""},
        {"timeline_id": ""},
        {"title": " "},
        {"source_episode_ids": ["ep-1"]},
        {"metadata": {"when": object()}},
    ],
    ids=[
        "private", "department", "unknown-class", "plain-str-kind", "blank-ref", "empty-content",
        "empty-timeline", "blank-title", "list-episode-ids", "unserialisable-metadata",
    ],
)
def test_a_record_the_archive_must_not_hold_is_refused_when_built(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _record(**overrides)


def test_source_kinds_are_closed_and_none_is_an_episode() -> None:
    assert {kind.value for kind in SourceKind} == {
        "convergence_report", "published_report", "captains_log", "notebook_finding",
    }
    assert not any("episode" in kind.value for kind in SourceKind)
    assert PROMOTABLE_CLASSIFICATIONS == frozenset({"ship", "fleet"})
    assert _record(classification="fleet").classification == "fleet"  # premise: the gate admits both


async def test_promote_entry_takes_only_a_promotion_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        with pytest.raises(TypeError):
            await store.promote_entry({"timeline_id": "timeline-one"})  # type: ignore[arg-type]
        assert await store.count() == 0
    finally:
        await store.close()


def test_the_store_has_no_append_update_or_delete_and_names_its_writes() -> None:
    for name in ("append", "update", "delete"):
        assert not hasattr(ArchiveStore, name)
    public = {
        name for name in vars(ArchiveStore)
        if not name.startswith("_") and callable(getattr(ArchiveStore, name))
    }
    assert public == {
        "initialize", "close", "promote_entry", "record_generation", "erase_entry", "entry_by_id",
        "search", "get_recent", "count",
    }


# --- A8 to A11: the Captain's erasure -------------------------------------------------------------------------


async def test_erasure_deletes_the_row_and_leaves_only_a_content_free_marker(tmp_path: Path) -> None:
    probe = f"AD1341-ERASE-PROBE-{uuid.uuid4().hex}"
    title_probe = f"AD1341-TITLE-PROBE-{uuid.uuid4().hex}"
    erased = _record(
        source_kind=SourceKind.NOTEBOOK_FINDING, source_ref="notebooks/Chapel/coolant.md",
        title=title_probe, content=f"{probe} " * 8, author_callsign="Chapel",
    )
    kept = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(kept) is PromotionOutcome.CREATED
        assert await store.promote_entry(erased) is PromotionOutcome.CREATED
        entry_id = next(entry.id for entry in await store.get_recent() if entry.title == title_probe)
        assert await store.erase_entry(entry_id, "Captain's order: not for later crews") is True
        assert await store.entry_by_id(entry_id) is None
        assert [entry.title for entry in await store.get_recent()] == [kept.title]
    finally:
        await store.close()
    path = tmp_path / "archive.db"
    columns = [row[1] for row in _rows(path, "PRAGMA table_info(archive_erasures)")]
    assert columns == ["id", "entry_id", "timeline_id", "source_kind", "source_ref", "reason", "erased_at"]
    markers = _rows(
        path, "SELECT entry_id, timeline_id, source_kind, source_ref, reason, erased_at FROM archive_erasures",
    )
    assert len(markers) == 1
    assert markers[0][:5] == (
        entry_id, "timeline-one", "notebook_finding", "notebooks/Chapel/coolant.md",
        "Captain's order: not for later crews",
    )
    assert markers[0][5] > 0
    raw = path.read_bytes()
    assert kept.content.encode("utf-8") in raw  # premise: the bytes check reads real row content
    assert probe.encode("utf-8") not in raw  # secure_delete overwrote the freed cell
    assert title_probe.encode("utf-8") not in raw


@pytest.mark.parametrize(
    ("content", "timeline"),
    [(None, "timeline-one"), ("Revised after the erasure.", "timeline-one"), (None, "timeline-two")],
    ids=["same-content", "changed-content", "next-timeline"],
)
async def test_an_erased_source_is_not_promoted_again(tmp_path: Path, content: str | None, timeline: str) -> None:
    first = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(first) is PromotionOutcome.CREATED
        entry_id = (await store.get_recent())[0].id
        assert await store.erase_entry(entry_id, "Captain's order") is True
        again = _record(timeline_id=timeline, content=content or first.content)
        assert await store.promote_entry(again) is PromotionOutcome.ERASED
        assert await store.count() == 0
    finally:
        await store.close()


async def test_erasing_an_absent_entry_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await store.promote_entry(_record())
        assert await store.erase_entry(9999, "Captain's order") is False
        assert await store.count() == 1
    finally:
        await store.close()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive_erasures") == []


@pytest.mark.parametrize(
    ("entry_id", "reason"),
    [
        (1, ""), (1, "   "), (1, "x" * (ARCHIVE_REASON_MAX_CHARS + 1)), (1, None),
        (0, "Captain's order"), (True, "Captain's order"),
    ],
    ids=["empty", "blank", "too-long", "not-a-string", "zero-id", "bool-id"],
)
async def test_an_erasure_needs_a_reason_and_a_real_id(tmp_path: Path, entry_id: Any, reason: Any) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await store.promote_entry(_record())
        with pytest.raises(ValueError):
            await store.erase_entry(entry_id, reason)
        assert await store.count() == 1
    finally:
        await store.close()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive_erasures") == []


# --- A12: generations -----------------------------------------------------------------------------------------


async def test_a_generation_close_is_recorded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        promoted = await store.record_generation(GenerationRecord(
            timeline_id="timeline-one", reset_tier=2, outcome=GenerationOutcome.PROMOTED,
            created=3, present=1, erased=1, withheld=2,
        ))
        skipped = await store.record_generation(GenerationRecord(
            timeline_id="", reset_tier=3, outcome=GenerationOutcome.SKIPPED,
            reason="Captain: records already exported",
        ))
    finally:
        await store.close()
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT id, timeline_id, reset_tier, outcome, created_count, present_count, erased_count, "
        "withheld_count, reason FROM generations ORDER BY id",
    )
    assert rows == [
        (promoted, "timeline-one", 2, "promoted", 3, 1, 1, 2, ""),
        (skipped, "", 3, "skipped", 0, 0, 0, 0, "Captain: records already exported"),
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"reset_tier": 1},
        {"outcome": GenerationOutcome.SKIPPED},
        {"timeline_id": ""},
        {"created": -1},
        {"outcome": "promoted"},
        {"reset_tier": True},
    ],
    ids=["tier-1", "skipped-without-reason", "promoted-without-timeline", "negative-count", "str-outcome", "bool-tier"],
)
def test_an_invalid_generation_close_is_refused(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {"timeline_id": "timeline-one", "reset_tier": 2, "outcome": GenerationOutcome.PROMOTED}
    fields.update(overrides)
    with pytest.raises(ValueError):
        GenerationRecord(**fields)


# --- A13: the seam --------------------------------------------------------------------------------------------


async def test_the_oracle_reads_a_promoted_entry_across_the_seam(tmp_path: Path) -> None:
    record = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        await store.promote_entry(record)
        results = await OracleService(archive_store=store).query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    assert len(results) == 1
    assert results[0].source_tier == "archive"
    assert record.title in results[0].content
    assert results[0].metadata["timeline_id"] == "timeline-one"
    assert results[0].metadata["category"] == "convergence_report"


# --- A14 to A16 (Amendment A2): one transaction at a time (F1); ids beyond SQLite (F2) ------------------------

_SECOND_REF = "reports/convergence/convergence-20261023-000000.md"


def _closure() -> GenerationRecord:
    return GenerationRecord(
        timeline_id="timeline-one", reset_tier=2, outcome=GenerationOutcome.PROMOTED, created=1,
    )


async def _promoted_entry_id(store: ArchiveStore) -> int:
    assert await store.promote_entry(_record()) is PromotionOutcome.CREATED
    return (await store.get_recent())[0].id


def _refuse_generations(path: Path) -> None:
    """Make every ``generations`` insert fail inside the store: a database failure the store cannot prevent."""
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            "CREATE TRIGGER refuse_generations BEFORE INSERT ON generations "
            "BEGIN SELECT RAISE (ABORT, 'AD-1341 A2: injected failure'); END"
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize(
    "pair", ["erase-and-missing-erase", "missing-erase-and-promote", "missing-erase-and-generation"],
)
async def test_overlapping_writes_never_report_a_success_another_write_undid(tmp_path: Path, pair: str) -> None:
    """F1: what each overlapping call reports is what the file holds, read back with ``sqlite3``."""
    reason = "Captain's order"
    store = _store(tmp_path)
    await store.initialize()
    try:
        entry_id = await _promoted_entry_id(store)
        missing_id = entry_id + 1000
        if pair == "erase-and-missing-erase":
            results = await asyncio.gather(
                store.erase_entry(entry_id, reason), store.erase_entry(missing_id, reason),
            )
        elif pair == "missing-erase-and-promote":
            results = await asyncio.gather(
                store.erase_entry(missing_id, reason), store.promote_entry(_record(source_ref=_SECOND_REF)),
            )
        else:
            results = await asyncio.gather(store.erase_entry(missing_id, reason), store.record_generation(_closure()))
    finally:
        await store.close()
    path = tmp_path / "archive.db"
    if pair == "erase-and-missing-erase":
        assert results == [True, False]
        assert _rows(path, "SELECT id FROM archive") == []  # the erasure it reported is on disk
        assert _rows(path, "SELECT entry_id FROM archive_erasures") == [(entry_id,)]
    elif pair == "missing-erase-and-promote":
        assert results == [False, PromotionOutcome.CREATED]
        assert _rows(path, "SELECT source_ref FROM archive ORDER BY id") == [(_record().source_ref,), (_SECOND_REF,)]
        assert _rows(path, "SELECT id FROM archive_erasures") == []
    else:
        assert results[0] is False
        assert _rows(path, "SELECT id FROM generations") == [(results[1],)]


async def test_close_waits_for_a_write_in_progress(tmp_path: Path) -> None:
    """F1: ``close`` never ends a write's transaction; it waits for the commit."""
    store = _store(tmp_path)
    await store.initialize()
    try:
        entry_id = await _promoted_entry_id(store)
        results = await asyncio.wait_for(
            asyncio.gather(store.erase_entry(entry_id, "Captain's order"), store.close(), return_exceptions=True),
            timeout=30,
        )
    finally:
        await store.close()  # nothing left to close once the gathered close ran
    assert results == [True, None]
    path = tmp_path / "archive.db"
    assert _rows(path, "SELECT id FROM archive") == []
    assert _rows(path, "SELECT entry_id FROM archive_erasures") == [(entry_id,)]


async def test_a_failed_write_leaves_an_overlapping_erasure_intact(tmp_path: Path) -> None:
    """F1: a write that fails rolls back only itself, and its error still reaches its caller."""
    store = _store(tmp_path)
    await store.initialize()
    try:
        entry_id = await _promoted_entry_id(store)
        _refuse_generations(tmp_path / "archive.db")
        erased, failed = await asyncio.gather(
            store.erase_entry(entry_id, "Captain's order"), store.record_generation(_closure()),
            return_exceptions=True,
        )
    finally:
        await store.close()
    assert erased is True
    assert isinstance(failed, sqlite3.DatabaseError)  # premise: the injected failure reached the store
    path = tmp_path / "archive.db"
    assert _rows(path, "SELECT id FROM archive") == []
    assert _rows(path, "SELECT entry_id FROM archive_erasures") == [(entry_id,)]
    assert _rows(path, "SELECT id FROM generations") == []


@pytest.mark.parametrize("entry_id", [2**63 - 1, 2**63, 2**64], ids=["largest-rowid", "above-sqlite", "far-above"])
async def test_an_id_no_row_can_have_is_no_entry(tmp_path: Path, entry_id: int) -> None:
    """F2: an id above SQLite's largest rowid is a missing id (None, then False), not an ``OverflowError``."""
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _promoted_entry_id(store)
        assert await store.entry_by_id(entry_id) is None
        assert await store.erase_entry(entry_id, "Captain's order") is False
        assert await store.count() == 1
    finally:
        await store.close()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive_erasures") == []
```

### 7.5 `src/probos/config.py` (M2)

SEARCH:
```python
    return base / "archive.db"


class SensoriumConfig(BaseModel):
```
REPLACE:
```python
    return base / "archive.db"


def resolve_records_repo_path(records: RecordsConfig, data_dir: Path) -> Path:
    """Effective location of Ship's Records (AD-434), shared by startup and ``probos reset`` (AD-1341).

    ``repo_path`` is operator-overridable; empty means ``{data_dir}/ship-records``. One function, so the
    reset's promotion reads the records this vessel writes rather than a path computed a second time.
    """
    if records.repo_path:
        return Path(records.repo_path)
    return Path(data_dir) / "ship-records"


class SensoriumConfig(BaseModel):
```

### 7.6 `src/probos/startup/cognitive_services.py` (M2; behaviour unchanged)

SEARCH:
```python
            from probos.knowledge.records_store import RecordsStore

            rcfg = config.records
            if not rcfg.repo_path:
                rcfg = rcfg.model_copy(update={"repo_path": str(data_dir / "ship-records")})
            records_store = RecordsStore(rcfg, ontology=None)
```
REPLACE:
```python
            from probos.config import resolve_records_repo_path
            from probos.knowledge.records_store import RecordsStore

            # AD-1341: the default comes from the one resolver probos reset's promotion also reads.
            rcfg = config.records
            if not rcfg.repo_path:
                rcfg = rcfg.model_copy(update={"repo_path": str(resolve_records_repo_path(rcfg, data_dir))})
            records_store = RecordsStore(rcfg, ontology=None)
```

### 7.6b `docs/development/config-facade-baseline.yaml` (M2: the resolver is a new owned public name)

`resolve_records_repo_path` is a new public name of `probos.config`, owned as `resolve_archive_db_path` is (AD-1265's precedent). These two pairs are exactly what `python -P scripts/check_config_facade.py --update-baseline` writes on the M2 tree (orchestrator's dry run, 2026-10-22). Apply the pairs; do not regenerate the file to make a different failure go away. Then run `--check`.

SEARCH:
```yaml
  own_models: 227
  owned: 294
  public_names: 307
```
REPLACE:
```yaml
  own_models: 227
  owned: 295
  public_names: 308
```

SEARCH:
```yaml
  os: {kind: module, removable_in: e3, tier: incidental}
  resolve_archive_db_path: {kind: function, tier: owned}
  urllib: {kind: module, removable_in: e3, tier: incidental}
```
REPLACE:
```yaml
  os: {kind: module, removable_in: e3, tier: incidental}
  resolve_archive_db_path: {kind: function, tier: owned}
  resolve_records_repo_path: {kind: function, tier: owned}
  urllib: {kind: module, removable_in: e3, tier: incidental}
```

### 7.6c `tests/test_ad1270e1_config_facade.py` (M2: the four pinned counts)

Each SEARCH line occurs once in the file.

SEARCH:
```python
    assert counts["public_names"] == 307
```
REPLACE:
```python
    assert counts["public_names"] == 308  # AD-1341 S1 (#1569) adds resolve_records_repo_path (307 -> 308)
```

SEARCH:
```python
    assert counts["owned"] == 294
```
REPLACE:
```python
    assert counts["owned"] == 295  # AD-1341 S1 (#1569): resolve_records_repo_path is owned (294 -> 295)
```

SEARCH:
```python
    assert len(baseline["names"]) == 307
```
REPLACE:
```python
    assert len(baseline["names"]) == 308  # AD-1341 S1 (#1569): resolve_records_repo_path
```

SEARCH:
```python
    assert "names=307" in proc.stdout
```
REPLACE:
```python
    assert "names=308" in proc.stdout  # AD-1341 S1 (#1569): resolve_records_repo_path
```

### 7.7 New file: `src/probos/knowledge/archive_promotion.py` (M2)

```python
"""Ship's Archive promotion (AD-1341 S1): the records-only service that writes the Ship's Archive.

A Ship's Computer service. Agents never call it, and nothing else calls ``ArchiveStore.promote_entry``
(``tests/test_ad1341_s1_promotion.py`` holds that with a census). It lists Ship's Records, keeps each document
that meets its source's criterion (``source_kind_for``), reads it as an anonymous reader, withholds what is
narrower than ``ship`` or has nothing to archive, and promotes the rest with their provenance.

- Episodes are never a source: they are memory, governed by AD-1340.
- No model call: every criterion is a fixed rule on the document's path and frontmatter.
- No failure is swallowed. What a failure means is the caller's decision: ``probos reset`` refuses to wipe
  anything.
- Ship's Records carry no source-episode ids, so a records-sourced entry carries none (the lessons slice
  adds them).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from probos.knowledge.archive_store import (
    PROMOTABLE_CLASSIFICATIONS,
    ArchiveStore,
    PromotionOutcome,
    PromotionRecord,
    SourceKind,
)
from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

#: The identity the service reads Ship's Records as. Anonymous, never "captain": the store's own read rule
#: (BF-679) withholds private records, and department records outside their department, before the
#: classification gate below sees them.
ARCHIVE_READER = ""


def source_kind_for(path: str, frontmatter: Any) -> SourceKind | None:
    """The per-source criterion: the kind a Ship's Records document is promoted as, or None.

    - ``reports/convergence/`` written by ``system`` (AD-551's convergence step): a convergence report.
    - ``captains-log/`` written by ``captain``: the Captain's log.
    - any other ``reports/`` document whose status is ``published``: a published report.
    - ``notebooks/`` with a non-empty ``claim_id`` (a finding published through AD-1140's governed route) or
      whose status is ``published``: a notebook finding.

    Nothing else is promoted: manuals (seeded by the shipyard), duty logs, bills, consultations, creative work,
    drafts and an agent's working notes. Classification is a separate gate (C1), applied to what is read.
    """
    if type(frontmatter) is not dict:
        return None
    author = frontmatter.get("author")
    status = frontmatter.get("status")
    if path.startswith("reports/convergence/"):
        return SourceKind.CONVERGENCE_REPORT if author == "system" else None
    if path.startswith("captains-log/"):
        return SourceKind.CAPTAINS_LOG if author == "captain" else None
    if path.startswith("reports/"):
        return SourceKind.PUBLISHED_REPORT if status == "published" else None
    if path.startswith("notebooks/"):
        claim_id = frontmatter.get("claim_id")
        if (type(claim_id) is str and claim_id.strip()) or status == "published":
            return SourceKind.NOTEBOOK_FINDING
    return None


@dataclass(frozen=True)
class PromotionPlan:
    """What a run would promote, and what met its criterion but may not be archived. Building it writes nothing."""

    records: tuple[PromotionRecord, ...]
    withheld: tuple[str, ...]


@dataclass(frozen=True)
class PromotionReport:
    """What one run did, as Ship's Records paths, in the order the records were listed."""

    created: tuple[str, ...]
    present: tuple[str, ...]
    erased: tuple[str, ...]
    withheld: tuple[str, ...]


async def plan_promotion(records: RecordsStore, *, timeline_id: str) -> PromotionPlan:
    """The records a run would promote, attributed to ``timeline_id``. Reads Ship's Records; writes nothing.

    ``probos reset --dry-run`` lists this plan. A document is withheld when the anonymous read refuses it, when
    its body is empty, or when it is narrower than ``ship`` (C1: a later crew reads every archived entry). An
    empty ``timeline_id`` raises as soon as there is anything to promote.
    """
    selected: list[PromotionRecord] = []
    withheld: list[str] = []
    for listed in await records.list_entries():
        path = listed["path"]
        if source_kind_for(path, listed["frontmatter"]) is None:
            continue
        document = await records.read_entry(path, ARCHIVE_READER)
        if document is None:
            withheld.append(path)
            continue
        frontmatter = document["frontmatter"]
        kind = source_kind_for(path, frontmatter)
        content = document["content"]
        if kind is None or not content.strip():
            withheld.append(path)
            continue
        classification = frontmatter.get("classification")
        if type(classification) is not str or classification not in PROMOTABLE_CLASSIFICATIONS:
            withheld.append(path)  # C1: nothing narrower than ship reaches a later crew
            continue
        selected.append(
            PromotionRecord(
                timeline_id=timeline_id,
                source_kind=kind,
                source_ref=path,
                title=str(frontmatter.get("topic") or path.rsplit("/", 1)[-1].removesuffix(".md")),
                content=content,
                classification=classification,
                author_callsign=str(frontmatter.get("author") or ""),
                metadata={
                    "status": str(frontmatter.get("status") or ""),
                    "department": str(frontmatter.get("department") or ""),
                    "record_created": str(frontmatter.get("created") or ""),
                    "record_updated": str(frontmatter.get("updated") or ""),
                },
            )
        )
    return PromotionPlan(records=tuple(selected), withheld=tuple(withheld))


async def promote_ship_records(
    records: RecordsStore, archive: ArchiveStore, *, timeline_id: str,
) -> PromotionReport:
    """Promote every Ship's Records document that meets its criterion into the Ship's Archive.

    Idempotent: a second run, under this timeline or the next, archives nothing new. Any failure propagates
    after the store has rolled its transaction back; entries promoted before it stay, and a re-run finds
    them present.
    """
    plan = await plan_promotion(records, timeline_id=timeline_id)
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
    return PromotionReport(
        created=tuple(created), present=tuple(present), erased=tuple(erased), withheld=plan.withheld,
    )
```

### 7.8 New file: `tests/test_ad1341_s1_promotion.py` (M2)

```python
"""AD-1341 S1 M2 (#1569): the records-only promotion service and the shared records-path resolver.

Ship's Records are written through the store's own producers, as the vessel writes them (``write_entry`` as
AD-551's convergence step calls it, ``write_notebook`` as AD-1140's publish_finding calls it,
``append_captains_log``), and read back by a ``RecordsStore`` that is never initialised, which is what
``probos reset`` has on a stopped vessel. The archive is the real ``ArchiveStore`` through
``default_factory``; the end of the chain is the real ``OracleService``.
"""

from __future__ import annotations

import ast
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig, resolve_records_repo_path
from probos.knowledge.archive_promotion import (
    ARCHIVE_READER,
    PromotionReport,
    plan_promotion,
    promote_ship_records,
    source_kind_for,
)
from probos.knowledge.archive_store import ArchiveStore, SourceKind
from probos.knowledge.records_store import RecordsStore
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_CLAIM = {"claim_id": "c0ffee00c0ffee00", "contest_state": "uncontested"}
_PROMOTED = ("convergence", "captains-log", "published-report", "finding-ship", "finding-fleet")
_NOT_SELECTED = (
    "draft-report", "gap-report", "convergence-by-agent", "captains-log-by-agent", "manual", "creative",
    "duty-log", "plain-ship-notebook",
)
_WITHHELD = ("private", "department", "department-without-field", "empty-body")


def _records(repo: Path) -> RecordsStore:
    return RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))


def _archive(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


async def _write_corpus(repo: Path) -> dict[str, str]:
    """Every source the service promotes and each near miss it must not, as case id -> records path."""
    writer = _records(repo)
    paths: dict[str, str] = {}
    paths["convergence"] = await writer.write_entry(
        author="system", path="reports/convergence/convergence-20261022-000000.md",
        content="## Convergence Report\n\nThree officers independently traced the coolant drift.",
        message="AD-551: Convergence report (coolant)", classification="ship", tags=["convergence", "ad-551"],
    )
    paths["captains-log"] = await writer.append_captains_log("Set course for the Briar Patch; coolant drift logged.")
    paths["published-report"] = await writer.write_entry(
        author="LaForge", path="reports/engineering/warp-core-audit.md",
        content="Warp core audit: the coolant manifold is within tolerance.", message="audit",
        classification="ship", status="published", topic="warp-core-audit",
    )
    paths["finding-ship"] = await writer.write_notebook(
        callsign="Chapel", topic_slug="coolant-exposure-c0ffee00",
        content="Claim: coolant exposure explains the fatigue reports.", department="medical",
        classification="ship", extra_frontmatter=dict(_CLAIM),
    )
    paths["finding-fleet"] = await writer.write_notebook(
        callsign="Spock", topic_slug="sensor-ghosts-c0ffee01",
        content="Claim: sensor ghosts track coolant venting.", department="science",
        classification="fleet", extra_frontmatter=dict(_CLAIM),
    )
    # Near misses: each fails its source's criterion.
    paths["draft-report"] = await writer.write_entry(
        author="LaForge", path="reports/engineering/draft.md", content="Unreviewed coolant notes.",
        message="draft", classification="ship",
    )
    paths["gap-report"] = await writer.write_entry(
        author="system", path="reports/gap-reports/gap-1.md", content="Gap: no coolant sensor.",
        message="gap", classification="ship",
    )
    paths["convergence-by-agent"] = await writer.write_entry(
        author="Worf", path="reports/convergence/convergence-forged.md", content="Forged coolant convergence.",
        message="forged", classification="ship",
    )
    paths["captains-log-by-agent"] = await writer.write_entry(
        author="Worf", path="captains-log/2026-01-01.md", content="Not the Captain's coolant entry.",
        message="forged", classification="ship", status="published",
    )
    paths["manual"] = await writer.write_entry(
        author="shipyard", path="manuals/coolant.md", content="Coolant manual.", message="manual",
        classification="ship", status="published",
    )
    paths["creative"] = await writer.write_entry(
        author="Chapel", path="creative/Chapel/coolant-ode.md", content="An ode to coolant.", message="poem",
        classification="ship", status="published",
    )
    paths["duty-log"] = await writer.write_entry(
        author="Worf", path="duty-logs/watch-1.md", content="Coolant watch quiet.", message="log",
        classification="ship", status="published",
    )
    paths["plain-ship-notebook"] = await writer.write_notebook(
        callsign="Worf", topic_slug="coolant-musings", content="Musings on coolant.", classification="ship",
    )
    # Selected by their criterion, then withheld: narrower than ship (C1), or nothing to archive.
    paths["private"] = await writer.write_notebook(
        callsign="Chapel", topic_slug="private-coolant-c0ffee02", content="Claim: a private coolant note.",
        classification="private", extra_frontmatter=dict(_CLAIM),
    )
    paths["department"] = await writer.write_notebook(
        callsign="Ogawa", topic_slug="dept-coolant-c0ffee03", content="Claim: a department coolant note.",
        department="medical", classification="department", extra_frontmatter=dict(_CLAIM),
    )
    paths["department-without-field"] = await writer.write_notebook(
        callsign="Ogawa", topic_slug="dept-bare-c0ffee04", content="Claim: a department note with no department.",
        classification="department", extra_frontmatter=dict(_CLAIM),
    )
    paths["empty-body"] = await writer.write_notebook(
        callsign="Chapel", topic_slug="empty-c0ffee05", content="   ", classification="ship",
        extra_frontmatter=dict(_CLAIM),
    )
    return paths


async def _promote(tmp_path: Path, repo: Path, timeline_id: str = "timeline-one") -> PromotionReport:
    archive = _archive(tmp_path)
    await archive.initialize()
    try:
        return await promote_ship_records(_records(repo), archive, timeline_id=timeline_id)
    finally:
        await archive.close()


# --- P1: premise 2 --------------------------------------------------------------------------------------------


async def test_ship_records_read_offline_without_initialize(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    reader = _records(repo)  # never initialised: probos reset reads the records of a stopped vessel
    assert set(paths.values()) <= {entry["path"] for entry in await reader.list_entries()}
    document = await reader.read_entry(paths["convergence"], ARCHIVE_READER)
    assert document is not None and "coolant drift" in document["content"]
    assert await reader.read_entry(paths["private"], ARCHIVE_READER) is None
    assert not (repo / ".git").exists()


# --- P2 to P5: the criteria and the gate ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "kind"),
    [
        ("convergence", SourceKind.CONVERGENCE_REPORT),
        ("captains-log", SourceKind.CAPTAINS_LOG),
        ("published-report", SourceKind.PUBLISHED_REPORT),
        ("finding-ship", SourceKind.NOTEBOOK_FINDING),
        ("finding-fleet", SourceKind.NOTEBOOK_FINDING),
    ],
    ids=["convergence", "captains-log", "published-report", "finding-ship", "finding-fleet"],
)
async def test_each_source_is_promoted_with_its_provenance(tmp_path: Path, case: str, kind: SourceKind) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    report = await _promote(tmp_path, repo)
    assert paths[case] in report.created
    document = await _records(repo).read_entry(paths[case], "captain")
    frontmatter = document["frontmatter"]
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT timeline_id, source_kind, category, classification, author_callsign, content, content_sha256, "
        "source_episode_ids, author_did FROM archive WHERE source_ref = ?",
        (paths[case],),
    )
    assert rows == [(
        "timeline-one", kind.value, kind.value, frontmatter["classification"], frontmatter["author"],
        document["content"], hashlib.sha256(document["content"].encode("utf-8")).hexdigest(), "[]", "",
    )]


@pytest.mark.parametrize("case", _NOT_SELECTED)
async def test_what_fails_its_criterion_is_not_promoted(tmp_path: Path, case: str) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    report = await _promote(tmp_path, repo)
    assert paths[case] not in report.created + report.present + report.erased + report.withheld
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths[case],)) == []


@pytest.mark.parametrize("case", _WITHHELD)
async def test_what_is_narrower_than_ship_or_empty_is_withheld_and_the_run_goes_on(tmp_path: Path, case: str) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    report = await _promote(tmp_path, repo)
    assert paths[case] in report.withheld
    assert sorted(report.created) == sorted(paths[name] for name in _PROMOTED)
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths[case],)) == []


@pytest.mark.parametrize("timeline", ["timeline-one", "timeline-two"], ids=["same-timeline", "next-timeline"])
async def test_a_second_run_archives_nothing_new(tmp_path: Path, timeline: str) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    first = await _promote(tmp_path, repo)
    second = await _promote(tmp_path, repo, timeline_id=timeline)
    assert sorted(first.created) == sorted(paths[name] for name in _PROMOTED)
    assert second.created == ()
    assert sorted(second.present) == sorted(first.created)
    assert len(_rows(tmp_path / "archive.db", "SELECT id FROM archive")) == len(_PROMOTED)
    assert {row[0] for row in _rows(tmp_path / "archive.db", "SELECT timeline_id FROM archive")} == {"timeline-one"}


# --- P6 to P10: edges -----------------------------------------------------------------------------------------


async def test_an_absent_records_directory_promotes_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "no-records"
    report = await _promote(tmp_path, missing, timeline_id="")
    assert report == PromotionReport(created=(), present=(), erased=(), withheld=())
    assert not missing.exists()


async def test_a_source_the_captain_erased_is_reported_and_not_archived_again(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    await _promote(tmp_path, repo)
    [(entry_id,)] = _rows(
        tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths["convergence"],),
    )
    archive = _archive(tmp_path)
    await archive.initialize()
    try:
        assert await archive.erase_entry(entry_id, "Captain's order") is True
        report = await promote_ship_records(_records(repo), archive, timeline_id="timeline-two")
    finally:
        await archive.close()
    assert report.erased == (paths["convergence"],)
    assert report.created == ()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths["convergence"],)) == []


async def test_a_failed_write_propagates(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    await _write_corpus(repo)
    with pytest.raises(RuntimeError, match="not initialized"):
        await promote_ship_records(_records(repo), _archive(tmp_path), timeline_id="timeline-one")


async def test_records_to_promote_need_a_timeline(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    await _write_corpus(repo)
    with pytest.raises(ValueError, match="timeline_id"):
        await plan_promotion(_records(repo), timeline_id="")


async def test_planning_reads_ship_records_and_writes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    plan = await plan_promotion(_records(repo), timeline_id="timeline-one")
    assert sorted(record.source_ref for record in plan.records) == sorted(paths[name] for name in _PROMOTED)
    assert sorted(plan.withheld) == sorted(paths[name] for name in _WITHHELD)
    assert {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()} == before
    assert not (tmp_path / "archive.db").exists()


@pytest.mark.parametrize("frontmatter", ["a scalar", ["a", "list"], None], ids=["scalar", "list", "none"])
def test_a_document_without_mapping_frontmatter_is_never_a_source(frontmatter: Any) -> None:
    assert source_kind_for("reports/convergence/convergence-x.md", {"author": "system"}) is (
        SourceKind.CONVERGENCE_REPORT
    )  # premise: the same path with mapping frontmatter is a source
    assert source_kind_for("reports/convergence/convergence-x.md", frontmatter) is None


# --- P11: the chain -------------------------------------------------------------------------------------------


async def test_a_promoted_record_reaches_a_later_crews_oracle(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    await _write_corpus(repo)
    await _promote(tmp_path, repo)
    later = _archive(tmp_path)  # the next generation's boot opens the same file
    await later.initialize()
    try:
        results = await OracleService(archive_store=later).query("coolant drift", tiers=["archive"])
    finally:
        await later.close()
    assert results, "premise: the query reaches the archive tier"
    assert {result.metadata["timeline_id"] for result in results} == {"timeline-one"}
    assert any("convergence-20261022-000000" in result.content for result in results)


# --- P12 to P15: the resolver, the layer and the census -------------------------------------------------------


@pytest.mark.parametrize("override", [False, True], ids=["default", "override"])
def test_the_records_path_has_one_resolver(tmp_path: Path, override: bool) -> None:
    data_dir = tmp_path / "data"
    configured = str(tmp_path / "elsewhere" / "records") if override else ""
    resolved = resolve_records_repo_path(RecordsConfig(repo_path=configured), data_dir)
    assert resolved == (Path(configured) if override else data_dir / "ship-records")


def test_startup_reads_the_records_path_through_the_shared_resolver() -> None:
    """D10: one resolver, so ``probos reset`` reads the records this vessel writes.

    A structural pin on purpose: the startup branch runs inside the boot sequence, which no focused test
    reaches, and the property is that the default is not computed a second time.
    """
    source = (_SRC / "startup" / "cognitive_services.py").read_text(encoding="utf-8")
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "resolve_records_repo_path"
    ]
    assert len(calls) == 1
    assert '"ship-records"' not in source


def test_the_service_imports_only_the_knowledge_layer() -> None:
    tree = ast.parse((_SRC / "knowledge" / "archive_promotion.py").read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert {name for name in modules if name.split(".")[0] == "probos"} == {
        "probos.knowledge.archive_store",
        "probos.knowledge.records_store",
    }


def test_only_the_promotion_service_writes_the_archive() -> None:
    """Agents never write the archive: ``promote_entry`` is named in ``src`` (called, referenced or spelled as a
    string) by the promotion service alone, beside its definition."""
    naming: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "promote_entry") or (
                isinstance(node, ast.Constant) and node.value == "promote_entry"
            ):
                naming.add(path.relative_to(_SRC).as_posix())
    assert naming == {"knowledge/archive_promotion.py"}
```

### 7.9 `src/probos/__main__.py` (M3: the reset promotes first, under the AD-816 pidfile; `probos archive erase`)

Eight pairs, in file order. Pair 5 re-indents the tier loop and the git commit by four spaces inside the pidfile's `try`. Their text is otherwise byte-identical, and they stay in `_cmd_reset`'s scope (the BF-892 site key). No block includes `__main__.py:2887` (the existing `console = Console()`).

Pair 1 (the annotation-only imports):

SEARCH:
```python
if TYPE_CHECKING:
    import httpx


def _default_data_dir() -> Path:
```
REPLACE:
```python
if TYPE_CHECKING:
    import httpx

    from probos.config import SystemConfig
    from probos.knowledge.archive_store import ArchiveStore
    from probos.knowledge.records_store import RecordsStore


def _default_data_dir() -> Path:
```

Pair 2 (the signature and docstring):

SEARCH:
```python
    console.print("\n  [dim][DRY RUN] No changes made.[/dim]")


def _cmd_reset(args: argparse.Namespace) -> None:
    """Handle ``probos reset`` — tiered reset system (BF-070)."""
```
REPLACE:
```python
    console.print("\n  [dim][DRY RUN] No changes made.[/dim]")


def _cmd_reset(args: argparse.Namespace) -> int:
    """Handle ``probos reset`` — tiered reset system (BF-070). Returns the exit code (AD-1341 S1).

    0 done, declined or a dry run; 1 refused with nothing deleted (a vessel owns the data directory, or the
    Ship's Archive promotion of a tier 2 or 3 reset failed); 2 a ``--skip-promotion`` without a usable reason.
    At tier 2 and above what the crew published is promoted into the Ship's Archive before the tier loop.
    """
```

Pair 3 (`--skip-promotion`, checked first):

SEARCH:
```python
    # Resolve the effective tier
    tier = _resolve_tier(args)

    # AD-418: Check for active scheduled tasks that survive reset
```
REPLACE:
```python
    # Resolve the effective tier
    tier = _resolve_tier(args)

    # AD-1341 S1: --skip-promotion REASON is checked before anything is read, locked or deleted.
    skip_reason = getattr(args, 'skip_promotion', None)
    if skip_reason is not None:
        problem = _skip_promotion_problem(skip_reason, tier)
        if problem:
            console.print(f"[red]✗[/red] {problem}")
            return 2

    # AD-418: Check for active scheduled tasks that survive reset
```

Pair 4 (the dry run lists the plan; no pidfile, no archive):

SEARCH:
```python
    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        _show_dry_run(tier, data_dir, active_task_count, console)
        return
```
REPLACE:
```python
    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        _show_dry_run(tier, data_dir, active_task_count, console)
        if tier >= 2:  # AD-1341 S1: the promotion plan; reads Ship's Records, opens no archive, takes no pidfile
            return _show_promotion_plan(config, data_dir, skip_reason, console)
        return 0
```

Pair 5 (the pidfile, the promotion, the tier loop re-indented, the release):

SEARCH:
```python
    # Confirmation prompt (skipped with -y)
    if not getattr(args, 'yes', False):
        if not _show_confirmation_prompt(tier, data_dir, active_task_count, console):
            console.print("[dim]Aborted.[/dim]")
            return

    # ── Execute reset ──
    tier_counts: dict[int, int] = {}
    total_freed: int = 0
    archive_path: Path | None = None

    for t in range(1, tier + 1):
        tier_def = RESET_TIERS[t]
        count = 0

        # Archive files first (ward_room.db at Tier 4)
        for fname in tier_def.get("archive_first", []):
            fpath = data_dir / fname
            if fpath.is_file():
                archive_dir = data_dir / "archives"
                archive_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                archive_path = archive_dir / f"{fpath.stem}_{timestamp}{fpath.suffix}"
                shutil.copy2(str(fpath), str(archive_path))

        # AD-541f: Record reset eviction before deleting files
        if t >= 2:
            _audit_db = data_dir / "eviction_audit.db"
            if _audit_db.is_file():
                try:
                    import sqlite3 as _sqlite3
                    import time as _time
                    import uuid as _uuid
                    _aconn = _sqlite3.connect(str(_audit_db))
                    _aconn.execute(
                        "INSERT INTO eviction_audit "
                        "(id, episode_id, agent_id, timestamp, reason, process, "
                        "details, content_hash, episode_timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (_uuid.uuid4().hex, "*", "*", _time.time(),
                         "reset", "probos_reset",
                         f"Tier {tier} reset — total episodic memory wipe",
                         "", 0.0),
                    )
                    _aconn.commit()
                    _aconn.close()
                except Exception:
                    pass  # Best-effort — reset must proceed

        # Delete files
        for fname in tier_def.get("files", []):
            fpath = data_dir / fname
            if fpath.is_file():
                total_freed += fpath.stat().st_size
                fpath.unlink()
                count += 1

        # Delete directories
        for dname in tier_def.get("dirs", []):
            dpath = data_dir / dname
            if dpath.is_dir():
                for fp in dpath.glob("*"):
                    if fp.is_file():
                        total_freed += fp.stat().st_size
                        fp.unlink()
                    elif fp.is_dir():
                        shutil.rmtree(fp, onerror=_force_remove_readonly)
                count += 1

        # Special cleanup
        for special in tier_def.get("special", []):
            if special == "chromadb_uuid_dirs":
                for uuid_dir in _find_chromadb_uuid_dirs(data_dir):
                    shutil.rmtree(uuid_dir, onerror=_force_remove_readonly)
                    count += 1
            elif special == "knowledge_subdirs":
                # Clear KnowledgeStore subdirectories (json/py files)
                for sub in _RESET_SUBDIRS:
                    sub_dir = repo_path / sub
                    if not sub_dir.is_dir():
                        continue
                    for fp in sub_dir.glob("*"):
                        if fp.is_file() and fp.suffix in (".json", ".py"):
                            fp.unlink()
                    count += 1
            elif special == "ontology_instance_id":
                instance_id_file = data_dir / "ontology" / "instance_id"
                if instance_id_file.is_file():
                    instance_id_file.unlink()
                    count += 1

        tier_counts[t] = count

    # Git commit if repo is git-initialized
    if (repo_path / ".git").is_dir():
        try:
            subprocess.run(
                ["git", "-C", str(repo_path), "add", "-A"],
                env=trusted_command_env(),
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            subprocess.run(
                ["git", "-C", str(repo_path), "commit", "-m",
                 f"probos reset: Tier {tier} — {RESET_TIERS[tier]['name']}"],
                env=trusted_command_env(),
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
        except Exception:
            pass  # Best-effort git commit during reset

    # ── Summary output ──
```
REPLACE:
```python
    # Confirmation prompt (skipped with -y)
    if not getattr(args, 'yes', False):
        if not _show_confirmation_prompt(tier, data_dir, active_task_count, console):
            console.print("[dim]Aborted.[/dim]")
            return 0

    # AD-1341 S1 (D12): every executing reset holds the AD-816 pidfile `probos serve` takes for this data directory,
    # so no vessel writes beside the reset or boots into it half done. A live owner refuses it.
    from rich.markup import escape

    from probos.pidfile_guard import AnotherInstanceRunning, acquire_pidfile

    try:
        reset_pidfile = acquire_pidfile(data_dir)
    except AnotherInstanceRunning as exc:
        console.print(f"[red]✗[/red] {escape(str(exc))}")
        console.print("[yellow]probos reset refused: stop the vessel first. Nothing was changed.[/yellow]")
        return 1
    try:
        # AD-1341 S1: what the crew published is promoted before anything is deleted; any failure refuses.
        promote_first = tier >= 2  # AD-1341 S1: tier 1 keeps the crew, so it has nothing to promote
        if promote_first and not _promote_before_reset(config, tier, data_dir, skip_reason, console):
            console.print("[red]✗[/red] probos reset refused before deleting anything.")
            return 1  # AD-1341 S1: refused before the tier loop; nothing was deleted

        # ── Execute reset ──
        tier_counts: dict[int, int] = {}
        total_freed: int = 0
        archive_path: Path | None = None

        for t in range(1, tier + 1):
            tier_def = RESET_TIERS[t]
            count = 0

            # Archive files first (ward_room.db at Tier 4)
            for fname in tier_def.get("archive_first", []):
                fpath = data_dir / fname
                if fpath.is_file():
                    archive_dir = data_dir / "archives"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                    archive_path = archive_dir / f"{fpath.stem}_{timestamp}{fpath.suffix}"
                    shutil.copy2(str(fpath), str(archive_path))

            # AD-541f: Record reset eviction before deleting files
            if t >= 2:
                _audit_db = data_dir / "eviction_audit.db"
                if _audit_db.is_file():
                    try:
                        import sqlite3 as _sqlite3
                        import time as _time
                        import uuid as _uuid
                        _aconn = _sqlite3.connect(str(_audit_db))
                        _aconn.execute(
                            "INSERT INTO eviction_audit "
                            "(id, episode_id, agent_id, timestamp, reason, process, "
                            "details, content_hash, episode_timestamp) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (_uuid.uuid4().hex, "*", "*", _time.time(),
                             "reset", "probos_reset",
                             f"Tier {tier} reset — total episodic memory wipe",
                             "", 0.0),
                        )
                        _aconn.commit()
                        _aconn.close()
                    except Exception:
                        pass  # Best-effort — reset must proceed

            # Delete files
            for fname in tier_def.get("files", []):
                fpath = data_dir / fname
                if fpath.is_file():
                    total_freed += fpath.stat().st_size
                    fpath.unlink()
                    count += 1

            # Delete directories
            for dname in tier_def.get("dirs", []):
                dpath = data_dir / dname
                if dpath.is_dir():
                    for fp in dpath.glob("*"):
                        if fp.is_file():
                            total_freed += fp.stat().st_size
                            fp.unlink()
                        elif fp.is_dir():
                            shutil.rmtree(fp, onerror=_force_remove_readonly)
                    count += 1

            # Special cleanup
            for special in tier_def.get("special", []):
                if special == "chromadb_uuid_dirs":
                    for uuid_dir in _find_chromadb_uuid_dirs(data_dir):
                        shutil.rmtree(uuid_dir, onerror=_force_remove_readonly)
                        count += 1
                elif special == "knowledge_subdirs":
                    # Clear KnowledgeStore subdirectories (json/py files)
                    for sub in _RESET_SUBDIRS:
                        sub_dir = repo_path / sub
                        if not sub_dir.is_dir():
                            continue
                        for fp in sub_dir.glob("*"):
                            if fp.is_file() and fp.suffix in (".json", ".py"):
                                fp.unlink()
                        count += 1
                elif special == "ontology_instance_id":
                    instance_id_file = data_dir / "ontology" / "instance_id"
                    if instance_id_file.is_file():
                        instance_id_file.unlink()
                        count += 1

            tier_counts[t] = count

        # Git commit if repo is git-initialized
        if (repo_path / ".git").is_dir():
            try:
                subprocess.run(
                    ["git", "-C", str(repo_path), "add", "-A"],
                    env=trusted_command_env(),
                    capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                )
                subprocess.run(
                    ["git", "-C", str(repo_path), "commit", "-m",
                     f"probos reset: Tier {tier} — {RESET_TIERS[tier]['name']}"],
                    env=trusted_command_env(),
                    capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                )
            except Exception:
                pass  # Best-effort git commit during reset
    finally:
        # AD-1341 S1: released on every exit. Left behind, it names a finished PID, which the next acquire removes.
        try:
            reset_pidfile.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            console.print(
                f"[yellow]⚠ The pidfile {escape(str(reset_pidfile))} was not removed: {escape(str(exc))}[/yellow]"
            )

    # ── Summary output ──
```

Pair 6 (the exit code, and the helpers before `_force_remove_readonly`):

SEARCH:
```python
    if active_task_count > 0:
        console.print(
            f"\n  [yellow]⚠ {active_task_count} scheduled task(s) active — "
            "routing may be degraded until Hebbian weights rebuild.[/yellow]"
        )


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
```
REPLACE:
```python
    if active_task_count > 0:
        console.print(
            f"\n  [yellow]⚠ {active_task_count} scheduled task(s) active — "
            "routing may be degraded until Hebbian weights rebuild.[/yellow]"
        )
    return 0


# ── AD-1341 S1: the Ship's Archive before a reset, and the Captain's erasure ──

#: Shown, never written: what a plan is attributed to when the ship has no instance id. A promotion needs one.
_UNATTRIBUTED_TIMELINE = "(no instance id)"


def _skip_promotion_problem(reason: str, tier: int) -> str:
    """Why ``--skip-promotion REASON`` cannot be used, or ``""``. Checked before anything is read or locked."""
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    if tier < 2:
        return "--skip-promotion applies to a reset of tier 2 or above; --soft promotes nothing."
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        return f"--skip-promotion needs a reason of 1 to {ARCHIVE_REASON_MAX_CHARS} characters."
    return ""


def _read_instance_id(data_dir: Path) -> str:
    """The ship's instance id (``ontology/instance_id``, stripped), or ``""`` when there is none.

    The generation a reset closes is attributed to it, and tier 2 deletes the file, so a reset reads it before
    the tier loop. It is the file the ontology loader writes on a vessel's first boot.
    """
    id_file = data_dir / "ontology" / "instance_id"
    if not id_file.is_file():
        return ""
    return id_file.read_text(encoding="utf-8").strip()


def _reset_records_store(config: SystemConfig, data_dir: Path) -> RecordsStore:
    """Ship's Records at the path this vessel writes (D10's resolver), never initialised: reading needs no git."""
    from probos.config import resolve_records_repo_path
    from probos.knowledge.records_store import RecordsStore

    records_path = resolve_records_repo_path(config.records, data_dir)
    return RecordsStore(config.records.model_copy(update={"repo_path": str(records_path)}), ontology=None)


def _configured_archive_store(config: SystemConfig) -> ArchiveStore:
    """The Ship's Archive at the path startup opens (AD-1265's resolver), not yet initialised.

    Only the computed default's directory is created, as startup does; an operator's path is used as given.
    """
    from probos.config import resolve_archive_db_path
    from probos.knowledge.archive_store import ArchiveStore
    from probos.storage.sqlite_factory import default_factory

    archive_path = resolve_archive_db_path(config.archive)
    if not config.archive.db_path:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveStore(str(archive_path), connection_factory=default_factory)


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


async def _promote_into_archive(
    config: SystemConfig, tier: int, data_dir: Path, timeline_id: str, skip_reason: str | None,
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
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        if skip_reason is not None:
            skipped = GenerationRecord(
                timeline_id=timeline_id, reset_tier=tier, outcome=GenerationOutcome.SKIPPED, reason=skip_reason,
            )
            await archive.record_generation(skipped)
            return True, f"Ship's Archive promotion skipped; the reason is recorded: {skip_reason.strip()}"
        promoted = await promote_ship_records(records, archive, timeline_id=timeline_id)
        closed = GenerationRecord(
            timeline_id=timeline_id, reset_tier=tier, outcome=GenerationOutcome.PROMOTED,
            created=len(promoted.created), present=len(promoted.present), erased=len(promoted.erased),
            withheld=len(promoted.withheld),
        )
        await archive.record_generation(closed)
    finally:
        await archive.close()
    return True, (
        f"Ship's Archive: {len(promoted.created)} promoted, {len(promoted.present)} already archived, "
        f"{len(promoted.erased)} erased by the Captain, {len(promoted.withheld)} withheld (timeline {timeline_id})."
    )


def _show_promotion_plan(config: SystemConfig, data_dir: Path, skip_reason: str | None, console: Console) -> int:
    """``--dry-run`` at tier 2 or above: what the reset would promote. Reads Ship's Records; opens no archive.

    0 when the plan was shown (a reset that would refuse says so); 1 when Ship's Records could not be read.
    """
    from rich.markup import escape

    from probos.knowledge.archive_promotion import plan_promotion

    if not config.archive.enabled:
        console.print("\n  [dim]The Ship's Archive is disabled (archive.enabled): nothing would be promoted.[/dim]")
        return 0
    if skip_reason is not None:
        console.print(f"\n  Ship's Archive promotion would be skipped, recording: {escape(skip_reason.strip())}")
        return 0
    try:
        timeline_id = _read_instance_id(data_dir)
        plan = asyncio.run(
            plan_promotion(_reset_records_store(config, data_dir), timeline_id=timeline_id or _UNATTRIBUTED_TIMELINE)
        )
    except Exception as exc:  # the dry run reports it; nothing is touched either way
        console.print(
            f"[red]✗[/red] The promotion plan could not be read: {escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return 1
    console.print(f"\n  Ship's Archive plan for timeline {escape(timeline_id or _UNATTRIBUTED_TIMELINE)}:")
    console.print(f"    {len(plan.records)} to promote, {len(plan.withheld)} withheld")
    for record in plan.records:
        console.print(f"    + {escape(record.source_ref)}")
    for path in plan.withheld:
        console.print(f"    - withheld: {escape(path)}")
    if plan.records and not timeline_id:
        console.print("  [yellow]⚠ No instance id: this reset would refuse without --skip-promotion REASON.[/yellow]")
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    """Handle ``probos archive erase ENTRY_ID --reason TEXT`` (AD-1341 S1): the Captain's erasure.

    The row is deleted and its bytes overwritten (``secure_delete``). A marker keeps the entry's id, timeline,
    source kind and ref, the reason and the time, never its title or content, and keeps that source from being
    promoted again. 0 erased or declined; 1 no such entry, or the erasure failed; 2 the archive disabled, or a
    bad id or reason. Plain ``print``: the entry's title and the reason are shown as text, never as markup.
    """
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    if getattr(args, "archive_cmd", None) != "erase":
        print("usage: probos archive erase ENTRY_ID --reason TEXT [--yes] [--config PATH]")
        return 2
    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): there is nothing to erase.")
        return 2
    entry_id, reason = args.entry_id, args.reason
    if entry_id <= 0:
        print("An archive entry id is a positive integer.")
        return 2
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        print(f"--reason needs 1 to {ARCHIVE_REASON_MAX_CHARS} characters. Do not restate the entry's content.")
        return 2
    try:
        return asyncio.run(_erase_archive_entry(config, entry_id, reason, bool(getattr(args, "yes", False))))
    except Exception as exc:  # one transaction, so nothing is half-erased; the Captain sees why
        print(f"The erasure failed: {type(exc).__name__}: {exc}")
        return 1


async def _erase_archive_entry(config: SystemConfig, entry_id: int, reason: str, confirmed: bool) -> int:
    """Show the entry, ask unless ``--yes``, then erase it. The archive is closed on every exit."""
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        entry = await archive.entry_by_id(entry_id)
        if entry is None:
            print(f"No Ship's Archive entry has id {entry_id}.")
            return 1
        print(f"Ship's Archive entry {entry.id}: {entry.title}")
        print(f"  source: {entry.source_kind or '(no provenance: an AD-524 entry)'} {entry.source_ref}")
        print(f"  timeline: {entry.timeline_id}")
        if not confirmed and input("  Erase it? [y/N]: ").strip().lower() != "y":
            print("Aborted. Nothing was erased.")
            return 0
        if not await archive.erase_entry(entry_id, reason):
            print(f"No Ship's Archive entry has id {entry_id}.")
            return 1
    finally:
        await archive.close()
    print(
        f"Erased Ship's Archive entry {entry_id}. A marker records the erasure: if its source is still in Ship's "
        "Records, it will not be promoted again."
    )
    return 0


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
```

Pair 7 (the parser):

SEARCH:
```python
    reset_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")

    args = parser.parse_args()
```
REPLACE:
```python
    reset_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")
    reset_parser.add_argument(
        "--skip-promotion", type=str, default=None, metavar="REASON",
        help="AD-1341: reset without promoting Ship's Records into the Ship's Archive first; "
             "the reason (1-500 characters) is recorded",
    )

    # --- probos archive (AD-1341 S1): the Captain's erasure ---
    archive_parser = subparsers.add_parser("archive", help="The Ship's Archive: the Captain's erasure (AD-1341)")
    archive_sub = archive_parser.add_subparsers(dest="archive_cmd", required=True)
    archive_erase = archive_sub.add_parser(
        "erase", help="Erase one Ship's Archive entry; its source is never promoted again",
    )
    archive_erase.add_argument("entry_id", type=int, help="The entry's id")
    archive_erase.add_argument(
        "--reason", type=str, required=True,
        help="Why, in 1-500 characters; it is recorded. Do not restate the entry's content.",
    )
    archive_erase.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_erase.add_argument("--config", "-c", type=Path, default=None, help="Path to config YAML")

    args = parser.parse_args()
```

Pair 8 (the dispatch):

SEARCH:
```python
    if args.command == "reset":
        _cmd_reset(args)
        return

    if args.command == "serve":
```
REPLACE:
```python
    if args.command == "reset":
        import sys
        sys.exit(_cmd_reset(args))  # AD-1341 S1: 1 refused, 2 a bad --skip-promotion

    if args.command == "archive":  # AD-1341 S1: the Captain's erasure
        import sys
        sys.exit(_cmd_archive(args))

    if args.command == "serve":
```

### 7.10 `tests/test_reset_integration.py` (M3: the shared helper's fake disables the archive)

`tests/test_ad1340_s1_restore_reset.py` and `tests/test_bf902_fts_reconciliation.py` import this helper. Two of bf902's callers are async, so the disabled archive is what keeps `_cmd_reset` from starting an event loop.

SEARCH:
```python
    args = _reset_args(data_dir, **flag_overrides)
    mock_config = MagicMock()
    mock_config.knowledge.repo_path = str(knowledge_dir)

    with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
        with patch("probos.__main__._default_data_dir", return_value=data_dir):
            _cmd_reset(args)
```
REPLACE:
```python
    args = _reset_args(data_dir, **flag_overrides)
    mock_config = MagicMock()
    mock_config.knowledge.repo_path = str(knowledge_dir)
    # AD-1341 S1 (#1569): a tier 2+ reset reads config.archive, and a MagicMock's `enabled` reads as True. These
    # tests exercise the tier loop; the promotion is tests/test_ad1341_s1_reset_and_erase.py's.
    mock_config.archive.enabled = False

    with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
        with patch("probos.__main__._default_data_dir", return_value=data_dir):
            assert _cmd_reset(args) == 0  # AD-1341 S1: _cmd_reset returns its exit code
```

### 7.11 `tests/test_distribution.py` (M3: six tier 2+ call sites disable the archive)

The tier 1 test (`test_tier1_soft_only_clears_transients`) is unchanged: tier 1 never reads `config.archive`.

SEARCH:
```python
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch
```
REPLACE:
```python
import tempfile
from pathlib import Path
from types import SimpleNamespace as _SimpleNamespace  # AD-1341 S1: the reset fakes' archive
from typing import Any
from unittest.mock import patch
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        # Tier 1+2 files cleared
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        # Tier 1+2 files cleared
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        # All tiers cleared
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        # All tiers cleared
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        # Same as Tier 4 — everything cleared
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        # Same as Tier 4 — everything cleared
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        # Everything should still exist
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a dry run of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        # Everything should still exist
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        assert not uuid_dir.exists()
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        assert not uuid_dir.exists()
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)  # Should not raise
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)  # Should not raise
```

### 7.12 `tests/test_proactive.py` (M3: the two tier 2+ tests disable the archive)

SEARCH:
```python
        args = self._reset_args(data_dir, full=True)

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)
```
REPLACE:
```python
        args = self._reset_args(data_dir, full=True)

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)
        mock_config.archive.enabled = False  # AD-1341 S1 (#1569): a tier 2+ reset reads config.archive
```

SEARCH:
```python
        args = self._reset_args(data_dir)  # default = Tier 2

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)
```
REPLACE:
```python
        args = self._reset_args(data_dir)  # default = Tier 2

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)
        mock_config.archive.enabled = False  # AD-1341 S1 (#1569): a tier 2+ reset reads config.archive
```

### 7.13 `tests/test_identity_deterministic.py` (M3: three tier 2 tests disable the archive)

SEARCH:
```python
import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
```
REPLACE:
```python
import argparse
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace as _SimpleNamespace  # AD-1341 S1: the reset fakes' archive (contract §12)
from unittest.mock import MagicMock, patch
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        assert not identity_db.exists(), "identity.db should be deleted after reset"
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        assert not identity_db.exists(), "identity.db should be deleted after reset"
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)

        assert not instance_id_file.exists(), "instance_id should be deleted after reset"
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)

        assert not instance_id_file.exists(), "instance_id should be deleted after reset"
```

SEARCH:
```python
                None,
            )
            _cmd_reset(args)  # Should not raise
```
REPLACE:
```python
                None,
            )
            # AD-1341 S1 (#1569): a reset of tier 2 or above reads config.archive; this fake predates it.
            mock_cfg.return_value[0].archive = _SimpleNamespace(enabled=False)
            _cmd_reset(args)  # Should not raise
```

### 7.14 New file: `tests/test_ad1341_s1_reset_and_erase.py` (M3)

```python
"""AD-1341 S1 M3 (#1569): ``probos reset`` promotes what the crew published before it deletes anything, and
``probos archive erase`` is the Captain's erasure.

Real objects throughout: the real ``_cmd_reset``, ``_cmd_archive`` and ``main`` on a temporary data directory; a
real ``SystemConfig`` whose archive is ``tmp_path / "archive.db"`` and whose knowledge repo is a temporary
directory, so no test touches ``~/.probos``; Ship's Records written by the store's own producers; the real
``ArchiveStore``, AD-816 pidfile and ``OracleService``. The config loader is the one stand-in: it returns that
``SystemConfig`` instead of reading YAML (``main``'s dispatch test also replaces the command it dispatches to).
The tests are synchronous because ``_cmd_reset`` runs its own event loop, as the CLI does.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sqlite3
from argparse import Namespace as _Namespace
from pathlib import Path
from typing import Any

import pytest

import probos
from probos import __main__ as cli
from probos.cognitive.oracle_service import OracleService
from probos.config import ArchiveConfig, KnowledgeConfig, RecordsConfig, SystemConfig
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.records_store import RecordsStore
from probos.pidfile_guard import is_pid_alive
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_SHIP = "ship-did-alpha-0001"
_NEXT_SHIP = "ship-did-beta-0002"
_CONVERGENCE = "reports/convergence/convergence-20261022-000000.md"
_CLAIM = {"claim_id": "c0ffee02c0ffee02", "contest_state": "uncontested"}


def _config(tmp_path: Path, *, archive_enabled: bool = True) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=archive_enabled, db_path=str(tmp_path / "archive.db"))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _data_dir(tmp_path: Path, *, instance_id: str = _SHIP) -> Path:
    """A stopped vessel's data directory: one file of each tier and, unless empty, the ship's instance id."""
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    if instance_id:
        (data_dir / "ontology" / "instance_id").write_text(f"{instance_id}\n", encoding="utf-8")
    for name in ("events.db", "trust.db", "ward_room.db"):  # tiers 1, 2 and 3
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


def _records(data_dir: Path) -> RecordsStore:
    return RecordsStore(RecordsConfig(repo_path=str(data_dir / "ship-records"), auto_commit=False))


async def _write_records(data_dir: Path) -> None:
    """Two sources the reset promotes and one the read rule withholds, written as the vessel writes them."""
    writer = _records(data_dir)
    await writer.write_entry(
        author="system", path=_CONVERGENCE,
        content="## Convergence Report\n\nThree officers independently traced the coolant drift.",
        message="AD-551: Convergence report (coolant)", classification="ship", tags=["convergence", "ad-551"],
    )
    await writer.append_captains_log("Set course for the Briar Patch; coolant drift logged.")
    await writer.write_notebook(
        callsign="Chapel", topic_slug="private-coolant-c0ffee02", content="Claim: a private coolant note.",
        classification="private", extra_frontmatter=dict(_CLAIM),
    )


def _archive_store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    """The real ``_cmd_reset`` with the loader returning ``config``; returns what it returns."""
    monkeypatch.setenv("COLUMNS", "200")  # Rich wraps at 80 columns off a terminal; the assertions read lines
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None,
    }
    values.update(flags)
    return cli._cmd_reset(_Namespace(**values))


def _erase(
    monkeypatch: pytest.MonkeyPatch, config: SystemConfig, entry_id: int, reason: str, *, yes: bool = True,
) -> Any:
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(_Namespace(archive_cmd="erase", entry_id=entry_id, reason=reason, yes=yes, config=None))


def _nothing_deleted(data_dir: Path) -> bool:
    return all((data_dir / name).is_file() for name in ("events.db", "trust.db", "ward_room.db"))


async def _oracle_query(tmp_path: Path, text: str) -> list[Any]:
    later = _archive_store(tmp_path)  # the next generation's boot opens the same file
    await later.initialize()
    try:
        return await OracleService(archive_store=later).query(text, tiers=["archive"])
    finally:
        await later.close()


# --- R1, R2: the reset promotes before it deletes ----------------------------------------------------------------


def test_a_tier2_reset_archives_under_the_ship_it_closes_then_deletes_its_instance_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    archive = tmp_path / "archive.db"
    assert set(_rows(archive, "SELECT timeline_id, source_kind FROM archive")) == {
        (_SHIP, "convergence_report"), (_SHIP, "captains_log"),
    }
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(1,)]
    assert _rows(
        archive, "SELECT timeline_id, reset_tier, outcome, created_count, withheld_count FROM generations",
    ) == [(_SHIP, 2, "promoted", 2, 1)]
    assert not (data_dir / "ontology" / "instance_id").exists()  # then the tier loop ran
    assert not (data_dir / "trust.db").exists()
    assert (data_dir / "ship-records" / _CONVERGENCE).is_file()  # tier 2 keeps Ship's Records
    assert not (data_dir / "probos.pid").exists()  # the reset released its pidfile


def test_a_full_reset_archives_before_ship_records_are_wiped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    assert (data_dir / "ship-records" / _CONVERGENCE).is_file()  # premise

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 0

    assert not list((data_dir / "ship-records").rglob("*.md"))  # tier 3 wiped Ship's Records ...
    archive = tmp_path / "archive.db"
    assert _rows(archive, "SELECT timeline_id FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(_SHIP,)]
    assert _rows(archive, "SELECT reset_tier, outcome FROM generations") == [(3, "promoted")]  # ... after promoting


# --- R3, R4, R4b: failure, the audited skip, and a skip without a reason ---------------------------------------


def test_a_failed_promotion_refuses_the_reset_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    connection = sqlite3.connect(str(tmp_path / "archive.db"))
    connection.execute("PRAGMA user_version = 7")  # an archive this ProbOS does not read: initialize refuses it
    connection.commit()
    connection.close()

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 1

    assert "RuntimeError" in capsys.readouterr().out
    assert _rows(tmp_path / "archive.db", "PRAGMA user_version") == [(7,)]
    assert _nothing_deleted(data_dir)
    assert (data_dir / "ontology" / "instance_id").read_text(encoding="utf-8").strip() == _SHIP
    assert not (data_dir / "probos.pid").exists()  # released on the refusal too


def test_skip_promotion_records_the_generation_and_archives_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, skip_promotion="  drill: nothing to keep ") == 0

    archive = tmp_path / "archive.db"
    assert _rows(archive, "SELECT COUNT(*) FROM archive") == [(0,)]
    assert _rows(archive, "SELECT timeline_id, reset_tier, outcome, reason FROM generations") == [
        (_SHIP, 2, "skipped", "drill: nothing to keep"),
    ]
    assert not (data_dir / "trust.db").exists()


@pytest.mark.parametrize(
    "flags",
    [{"skip_promotion": "   "}, {"skip_promotion": "x" * 501}, {"skip_promotion": "drill", "soft": True}],
    ids=["blank", "too-long", "soft"],
)
def test_a_skip_without_a_usable_reason_exits_2_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: dict[str, Any],
) -> None:
    data_dir = _data_dir(tmp_path)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, **flags) == 2

    assert _nothing_deleted(data_dir)
    assert not (tmp_path / "archive.db").exists()
    assert not (data_dir / "probos.pid").exists()  # refused before the pidfile


# --- R5, R6: tier 1 and the dry run never write the archive ----------------------------------------------------


def test_a_soft_reset_never_opens_the_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, soft=True) == 0

    assert not (data_dir / "events.db").exists()  # premise: the soft reset ran
    assert not (tmp_path / "archive.db").exists()
    assert (data_dir / "ontology" / "instance_id").is_file()


def test_a_dry_run_lists_the_plan_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    owner = str(os.getppid())
    (data_dir / "probos.pid").write_text(owner, encoding="utf-8")  # a live vessel: a dry run takes no pidfile

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "2 to promote, 1 withheld" in out
    assert "+ captains-log/" in out
    assert not (tmp_path / "archive.db").exists()
    assert _nothing_deleted(data_dir) and (data_dir / "ontology" / "instance_id").is_file()
    assert (data_dir / "probos.pid").read_text(encoding="utf-8") == owner


# --- R7, R8, R9: a live vessel, the archive disabled, no instance id -------------------------------------------


@pytest.mark.parametrize("flags", [{"soft": True}, {}, {"full": True}], ids=["soft", "default", "full"])
def test_a_live_vessel_refuses_every_executing_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: dict[str, Any],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    owner = os.getppid()
    assert owner != os.getpid() and is_pid_alive(owner)  # premise: a live process that is not this one
    (data_dir / "probos.pid").write_text(str(owner), encoding="utf-8")

    assert _reset(monkeypatch, _config(tmp_path), data_dir, **flags) == 1

    assert _nothing_deleted(data_dir)
    assert (data_dir / "probos.pid").read_text(encoding="utf-8") == str(owner)  # the owner's pidfile is kept
    assert not (tmp_path / "archive.db").exists()


def test_with_the_archive_disabled_the_reset_proceeds_and_erase_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path, archive_enabled=False)

    assert _reset(monkeypatch, config, data_dir) == 0

    assert "Ship's Archive is disabled" in capsys.readouterr().out
    assert not (data_dir / "trust.db").exists()
    assert not (tmp_path / "archive.db").exists()
    assert _erase(monkeypatch, config, 1, "superseded") == 2


@pytest.mark.parametrize("with_records", [True, False], ids=["with-records", "nothing-to-promote"])
def test_without_an_instance_id_records_to_promote_refuse_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_records: bool,
) -> None:
    data_dir = _data_dir(tmp_path, instance_id="")
    if with_records:
        asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == (1 if with_records else 0)

    assert (data_dir / "trust.db").is_file() is with_records
    assert not (tmp_path / "archive.db").exists()  # nothing attributed, and no generation recorded


# --- R10, R10b: the Captain's erasure ----------------------------------------------------------------------------


def test_the_captain_erases_an_entry_and_the_next_reset_does_not_bring_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir) == 0
    archive = tmp_path / "archive.db"
    (entry_id,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]

    assert _erase(monkeypatch, config, entry_id, "superseded by the Captain") == 0

    assert "will not be promoted again" in capsys.readouterr().out
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE id = ?", (entry_id,)) == [(0,)]
    assert _rows(archive, "SELECT entry_id, timeline_id, source_kind, source_ref, reason FROM archive_erasures") == [
        (entry_id, _SHIP, "convergence_report", _CONVERGENCE, "superseded by the Captain"),
    ]

    # The next crew's reset reads the same Ship's Records (tier 2 kept them) and does not archive it again.
    (data_dir / "ontology" / "instance_id").write_text(_NEXT_SHIP, encoding="utf-8")
    assert _reset(monkeypatch, config, data_dir) == 0
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(0,)]
    assert _rows(
        archive, "SELECT timeline_id, created_count, present_count, erased_count FROM generations ORDER BY id",
    ) == [(_SHIP, 2, 0, 0), (_NEXT_SHIP, 0, 1, 1)]


@pytest.mark.parametrize(
    ("entry_id", "reason", "answer", "code"),
    [(999, "superseded", "y", 1), (0, "superseded", "y", 2), (None, "   ", "y", 2), (None, "superseded", "n", 0)],
    ids=["no-such-entry", "zero-id", "blank-reason", "declined"],
)
def test_an_erasure_that_cannot_or_should_not_happen_erases_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_id: int | None, reason: str, answer: str, code: int,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir) == 0
    archive = tmp_path / "archive.db"
    (existing,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)

    assert _erase(monkeypatch, config, existing if entry_id is None else entry_id, reason, yes=False) == code

    assert _rows(archive, "SELECT COUNT(*) FROM archive") == [(2,)]
    assert _rows(archive, "SELECT COUNT(*) FROM archive_erasures") == [(0,)]


# --- R11, R12, R13: the census, the chain, the parser ------------------------------------------------------------


def test_only_the_cli_erases_an_entry_or_closes_a_generation() -> None:
    """``erase_entry`` and ``record_generation`` are named in ``src`` (called, referenced or spelled as a string)
    by ``__main__.py`` alone, beside the store's definitions: no agent or service erases or closes a generation."""
    naming: dict[str, set[str]] = {"erase_entry": set(), "record_generation": set()}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in naming:
                naming[node.attr].add(path.relative_to(_SRC).as_posix())
            elif isinstance(node, ast.Constant) and type(node.value) is str and node.value in naming:
                naming[node.value].add(path.relative_to(_SRC).as_posix())
    assert naming == {"erase_entry": {"__main__.py"}, "record_generation": {"__main__.py"}}


def test_a_later_crews_oracle_reads_what_the_reset_archived_under_the_old_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 0

    results = asyncio.run(_oracle_query(tmp_path, "coolant drift"))
    assert results, "premise: the query reaches the archive tier"
    assert {result.metadata["timeline_id"] for result in results} == {_SHIP}
    assert any("coolant drift" in result.content for result in results)


@pytest.mark.parametrize(
    ("argv", "command", "attribute", "value"),
    [
        (["reset", "--yes", "--skip-promotion", "drill"], "_cmd_reset", "skip_promotion", "drill"),
        (["archive", "erase", "7", "--reason", "superseded", "--yes"], "_cmd_archive", "entry_id", 7),
    ],
    ids=["reset", "archive-erase"],
)
def test_main_parses_the_new_arguments_and_exits_with_the_command_code(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], command: str, attribute: str, value: Any,
) -> None:
    seen: list[_Namespace] = []

    def _command(args: _Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, command, _command)
    monkeypatch.setattr("sys.argv", ["probos", *argv])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [getattr(args, attribute) for args in seen] == [value]
```

## 8. Tracking (tracker pairs; in M4's commit)

Written against `0e122174` and re-anchored by the orchestrator on `80456da2`, because BF-903 merged first: both pairs anchor on BF-903's head line and its *Reversal* bullet. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title, the blank line and the bold lead of BF-903's head entry):

SEARCH:
```markdown
# ProbOS Progress

**BF-903 (2026-10-22), closes #1581 -- a visiting officer's capabilities are checked where it acts, and the capability names have one owner.**
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1341 S1 (2026-10-22), #1569 slice 1 of 6 -- what the crew published survives a reset: `probos reset` promotes it into the Ship's Archive first, with provenance, and the Captain can erase an archive entry.** The Ship's Archive (AD-524) is at schema v1, migrated in place from v0. It gains provenance columns (source kind and ref, content SHA-256, classification, author DID, source episode ids), a partial unique index on `(source_kind, source_ref, content_sha256)`, and `generations` and `archive_erasures` tables; `secure_delete` is set and verified, and any other schema version is refused. `ArchiveStore.append` is gone. `promote_entry(PromotionRecord)` is the one write: idempotent across timelines, because Ship's Records survive a tier 2 reset. Only `ship` and `fleet` records can be built (C1). There is no episode source kind. `erase_entry` deletes a row and leaves a marker with no title, content or hash, which also keeps that source from being promoted again. The store's writes and its close take turns on its one connection, so no call's rollback can undo another's work, and an id beyond SQLite's range is simply no entry. The records-only service `knowledge/archive_promotion.py` promotes convergence reports, the Captain's log, published reports and governed notebook findings, read as the anonymous reader, with no model call; anything narrower than ship is withheld and reported. `config.resolve_records_repo_path` is the one records-path resolver. `probos reset` at tier 2 and above promotes before it wipes and refuses on any failure (exit 1). `--skip-promotion REASON` is recorded in `generations`, `--dry-run` lists the plan, and every executing reset holds the AD-816 pidfile and refuses beside a vessel started with `probos serve`. `probos archive erase ENTRY_ID --reason` is the Captain's erasure. New: `tests/test_ad1341_s1_archive_store.py`, `tests/test_ad1341_s1_promotion.py` and `tests/test_ad1341_s1_reset_and_erase.py` (the real store, records, Oracle and reset command). Updated where they pinned the old write or used partial config fakes: `test_ad524_ships_archive.py`, `test_reset_integration.py`, `test_distribution.py`, `test_proactive.py`, `test_identity_deterministic.py` and `test_ad1270e1_config_facade.py` (its name counts). The store-registry baseline row lists the two new tables, and the config-facade baseline lists `resolve_records_repo_path` as owned. The contract is `prompts/ad-1341-s1-archive-provenance-promotion.md`.

**BF-903 (2026-10-22), closes #1581 -- a visiting officer's capabilities are checked where it acts, and the capability names have one owner.**
```

**`DECISIONS.md`** (after BF-903's entry, anchored on its *Reversal* bullet, the blank line and the next heading; the docs-only commit adds a *Validation of record* bullet before AD-1341 S1's own *Reversal* line):

SEARCH:
```markdown
- *Reversal.* Revert the BF-903 commits. Nothing persisted changes; the facade stops checking visitors, any capability string is accepted again, a channel admits a sender whose pairing cannot be read and serves paired senders natural language again, and MCP dispatches whatever arguments it is sent.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-903 commits. Nothing persisted changes; the facade stops checking visitors, any capability string is accepted again, a channel admits a sender whose pairing cannot be read and serves paired senders natural language again, and MCP dispatches whatever arguments it is sent.

### AD-1341 S1 -- What the crew published is promoted into the Ship's Archive before a reset, with provenance, and the Captain can erase an archive entry (2026-10-22, #1569 slice 1 of 6)

- *Scope.* Slice 1 of #1569, in four milestone commits, one gate and one PR. Files: `knowledge/archive_store.py` (schema v1, `promote_entry`, `record_generation`, `erase_entry`, `entry_by_id`, the record types), new `knowledge/archive_promotion.py`, `config.py` (`resolve_records_repo_path`), `startup/cognitive_services.py`, `__main__.py` (`probos reset` promotion, `probos archive erase`), `docs/development/store-baseline.yaml`, `docs/development/config-facade-baseline.yaml` and tests. Contract: `prompts/ad-1341-s1-archive-provenance-promotion.md`. Later slices: S2 the inherited label, S3 the review queue and veto, S4 lessons and the stand-down, S5 after-action triggers and continuous promotion, S6 the `--full` snapshot and clean slate.
- *D3 (the key).* `(source_kind, source_ref, content_sha256)`, without the timeline. Ship's Records survive a tier 2 reset, so a key with the timeline would archive every surviving record again under each new timeline: false provenance, duplicates, and an erasure undone. A changed document is a new entry under the timeline that changed it.
- *D4-D6 (the store).* `promote_entry` is the one write (`append` is removed; `promote` was already a method name on two other classes); the erasure check and the insert are one statement. The contract types live in the store module and validate on construction with exact types; nothing narrower than `ship` can be built (C1). The migration is additive and idempotent, and `user_version` is written last; any other version is refused; `secure_delete` is verified. (A2) The writes and the close hold one store lock through their commit or rollback (AD-1340 R3's pattern): on the shared connection, one call's rollback undid another's work, which still reported success. An id above SQLite's largest rowid is no entry, not an error.
- *D7 (erasure).* The marker holds the entry id, timeline, source kind and ref, the reason and the time; never the title, content, metadata or hash. It blocks re-promotion of that source with any content, because the source still exists in Ship's Records.
- *D8 (criteria).* Convergence reports by `system`, the Captain's log by `captain`, other reports when `published`, notebooks with a `claim_id` (AD-1140) or `published`. Read as the anonymous reader; anything narrower than ship, or with an empty body, is withheld and reported. No model call; records carry no episode ids.
- *D11 (store registry).* The baseline row is updated, not declared: the archive lives outside `data_dir`, so its declaration is AD-1265's second-root question.
- *D12-D13 (the reset).* At tier 2 and above `probos reset` promotes before deleting and refuses on any failure (exit 1); without an instance id, records to promote also refuse. `--skip-promotion REASON` writes a `generations` row; a blank, over-long or tier 1 reason exits 2. Every executing reset holds the AD-816 pidfile, so it refuses beside a vessel started with `probos serve` (the interactive shell takes no pidfile: register). With the archive disabled the reset proceeds with a notice and `probos archive erase` exits 2.
- *C1.* Promoting at `ship` classification or above only stands; the Captain can overrule it.
- *Disclosed effects.* The live archive migrates to v1 on its next boot; an archive at another version is refused (the Oracle's archive tier off). `probos reset` can now refuse and exit 1, including `--soft` beside a running vessel. Erased bytes stay in earlier snapshots until they age out. A record first eligible in a later generation is attributed to that generation.
- *Reversal.* Revert the S1 commits. The archive file stays at v1: AD-524's code reads and writes it unchanged, since its statements name only v0 columns and the partial index excludes rows with no hash. Promoted rows, generations and markers stay until the Captain removes them. `probos reset` stops promoting and stops refusing beside a running vessel.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M4's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the code commits:** add a *Validation of record* bullet before AD-1341 S1's *Reversal* line: the mutation campaign of record, its base tree, the sha256 of each §10 file and each new test file, and each row's first failing test. Add the same as a closing section of this contract, then regenerate the ledger.

**`docs/development/roadmap.md`:** no row; `AD-1341` does not appear there.

## 9. What this does NOT change

- The Oracle's archive tier and its labels (S2). No review queue or veto (S3). No exit notes, lessons format or stand-down (S4). No dream step or continuous promotion (S5). No `--full` records snapshot, nature description entry or `--clean-slate` (S6).
- `RESET_TIERS` and every tier's file list; `archives/` handling; the Ward Room archive-first step.
- Episodes and `episode_archive.db` (AD-1340); `procedures/` (nature, kept).
- `RecordsStore` itself; `record_is_readable`; `publish_finding`; the AD-551 step.
- The AD-1265 backup roots and the AD-1266 restore; the store declarations (only the baseline row changes).
- `doctor/runner.py`'s `_default_data_dir` (register).
- (M3) `pidfile_guard.py` and `_serve`'s use of it; the interactive shell still takes no pidfile (register RA1-1); the `rebuild-episodic` and `backup-reclaim` probes.
- (M3) The tier loop's behaviour and its two git launches, `_show_dry_run`, `_show_confirmation_prompt` and every other subcommand.
- Federation sharing of the archive; trust scoring (the just-culture note goes to its next owner).

## 10. Mutation rows (46 rows: 36 for M1 and M2, 10 for M3; whole stripped lines, each occurring once in its file after §7)

Tier HIGH: every changed production file has rows. Run each row against `tests/test_ad1341_s1_archive_store.py` (rows K) or `tests/test_ad1341_s1_promotion.py` (rows P, C, S) on the contract-applied tree, after an unmutated baseline run that passes. Restore each file before the next row. Rows M-R run against `tests/test_ad1341_s1_reset_and_erase.py` on the tree with §7.9 to §7.14 applied.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| K1 | `src/probos/knowledge/archive_store.py` | `_PROMOTION_KEY = "source_kind, source_ref, content_sha256"` | `_PROMOTION_KEY = "timeline_id, source_kind, source_ref, content_sha256"` | A4 `[next-timeline]` (the second promotion returns CREATED). This is the orchestrator's "a key without timeline_id", inverted by D3 |
| K2 | `src/probos/knowledge/archive_store.py` | `"CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_promotion_key "` | `"CREATE INDEX IF NOT EXISTS idx_archive_promotion_key "` | A4 `[same-timeline]` (ON CONFLICT matches no unique index, so the promotion raises); also A1. "Drop the partial index" |
| K3 | `src/probos/knowledge/archive_store.py` | `await db.execute(_PROMOTION_INDEX)` | `pass` | A1 (the index assertion) |
| K4 | `src/probos/knowledge/archive_store.py` | `await db.execute("PRAGMA secure_delete=ON")` | `pass` | A1 (`initialize` refuses: the check reads 0). "Drop secure_delete"; A8's bytes check guards the check itself |
| K5 | `src/probos/knowledge/archive_store.py` | `if version not in (0, ARCHIVE_SCHEMA_VERSION):` | `if False:` | A3 `[later]` |
| K6 | `src/probos/knowledge/archive_store.py` | `if name not in present:` | `if True:` | A2 `[interrupted]` (duplicate column) |
| K7 | `src/probos/knowledge/archive_store.py` | `await db.execute(f"PRAGMA user_version = {ARCHIVE_SCHEMA_VERSION}")` | `pass` | A1 |
| K8 | `src/probos/knowledge/archive_store.py` | `created = cursor.rowcount == 1` | `created = True` | A4 `[same-timeline]` |
| K9 | `src/probos/knowledge/archive_store.py` | `erased = await cursor.fetchone() is not None` | `erased = False` | A9 `[same-content]` |
| K10 | `src/probos/knowledge/archive_store.py` | `"WHERE NOT EXISTS (SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ?) "` | `"WHERE NOT EXISTS (SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ? AND 0) "` | A9 `[changed-content]` |
| K11 | `src/probos/knowledge/archive_store.py` | `"SELECT id, timeline_id, source_kind, source_ref, ?, ? FROM archive WHERE id = ?"` | `"SELECT id, timeline_id, source_kind, content, ?, ? FROM archive WHERE id = ?"` | A8 (the marker equality). "A marker holding content" |
| K12 | `src/probos/knowledge/archive_store.py` | `await self._db.execute("DELETE FROM archive WHERE id = ?", (entry_id,))` | `pass` | A8 |
| K13 | `src/probos/knowledge/archive_store.py` | `if cursor.rowcount != 1:` | `if False:` | A10 (returns True) |
| K14 | `src/probos/knowledge/archive_store.py` | `if type(entry_id) is not int or entry_id <= 0:` | `if False:` | A11 `[zero-id]` (`[bool-id]` erases entry 1) |
| K15 | `src/probos/knowledge/archive_store.py` | `if type(reason) is not str or not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:` | `if False:` | A11 `[empty]` |
| K16 | `src/probos/knowledge/archive_store.py` | `if type(self.classification) is not str or self.classification not in PROMOTABLE_CLASSIFICATIONS:` | `if False:` | A6 `[private]` (C1 at the store) |
| K17 | `src/probos/knowledge/archive_store.py` | `if type(self.source_kind) is not SourceKind:` | `if False:` | A6 `[plain-str-kind]` |
| K18 | `src/probos/knowledge/archive_store.py` | `if self.outcome is GenerationOutcome.SKIPPED and not self.reason.strip():` | `if False:` | A12b `[skipped-without-reason]` |
| K19 | `src/probos/knowledge/archive_store.py` | `source_kind=row[9],` | `source_kind="",` | A4 (the entry assertion) |
| K20 | `src/probos/knowledge/archive_store.py` | `async with self._write_lock:  # AD-1341 F1: the insert and its erasure check commit or roll back alone` | `if True:` | A14 `[missing-erase-and-promote]` (CREATED, no second row). A2, D16 |
| K21 | `src/probos/knowledge/archive_store.py` | `async with self._write_lock:  # AD-1341 F1: the generation row commits or rolls back alone` | `if True:` | A14 `[missing-erase-and-generation]` (an id, no row); also A15. A2, D16 |
| K22 | `src/probos/knowledge/archive_store.py` | `async with self._write_lock:  # AD-1341 F1: the marker and the delete commit or roll back alone` | `if True:` | A14 `[erase-and-missing-erase]` (True, the row kept, no marker). A2, D16 |
| K23 | `src/probos/knowledge/archive_store.py` | `async with self._write_lock:  # AD-1341 F1: never close inside another call's transaction` | `if True:` | A14b (the erasure raises; `wait_for` bounds the run). A2, D16 |
| K24 | `src/probos/knowledge/archive_store.py` | `if entry_id > _SQLITE_MAX_ROWID:  # AD-1341 F2: no row has it, and SQLite cannot bind it` | `if False:` | A16 `[above-sqlite]` (`OverflowError` from `erase_entry`). A2, D17 |
| K25 | `src/probos/knowledge/archive_store.py` | `if not self._db or not 0 < entry_id <= _SQLITE_MAX_ROWID:  # AD-1341 F2: ids are positive rowids` | `if not self._db:` | A16 `[above-sqlite]` (`OverflowError` from `entry_by_id`). A2, D17 |
| P-R1 | `src/probos/knowledge/archive_promotion.py` | `return SourceKind.CONVERGENCE_REPORT if author == "system" else None` | `return SourceKind.CONVERGENCE_REPORT` | P3 `[convergence-by-agent]` |
| P-R2 | `src/probos/knowledge/archive_promotion.py` | `return SourceKind.CAPTAINS_LOG if author == "captain" else None` | `return SourceKind.CAPTAINS_LOG` | P3 `[captains-log-by-agent]` |
| P-R3 | `src/probos/knowledge/archive_promotion.py` | `return SourceKind.PUBLISHED_REPORT if status == "published" else None` | `return SourceKind.PUBLISHED_REPORT` | P3 `[draft-report]` (also `[gap-report]`) |
| P-R4 | `src/probos/knowledge/archive_promotion.py` | `if (type(claim_id) is str and claim_id.strip()) or status == "published":` | `if True:` | P3 `[plain-ship-notebook]` |
| P-R5 | `src/probos/knowledge/archive_promotion.py` | `if source_kind_for(path, listed["frontmatter"]) is None:` | `if False:` | P3 `[plain-ship-notebook]` (it lands in `withheld`) |
| P-R6 | `src/probos/knowledge/archive_promotion.py` | `if kind is None or not content.strip():` | `if kind is None:` | P4 `[empty-body]` (ValueError from the record; every corpus test also fails) |
| P-R7 | `src/probos/knowledge/archive_promotion.py` | `if type(classification) is not str or classification not in PROMOTABLE_CLASSIFICATIONS:` | `if False:` | P4 `[department-without-field]` (the run raises instead of withholding; every corpus test also fails). This replaces "read as captain" |
| P-R8 | `src/probos/knowledge/archive_promotion.py` | `outcome = await archive.promote_entry(record)` | `outcome = PromotionOutcome.PRESENT` | P2 |
| C-R1 | `src/probos/config.py` | `return Path(data_dir) / "ship-records"` | `return Path(data_dir) / "records"` | P12 `[default]` |
| C-R2 | `src/probos/config.py` | `if records.repo_path:` | `if False:` | P12 `[override]` |
| S-R1 | `src/probos/startup/cognitive_services.py` | `rcfg = rcfg.model_copy(update={"repo_path": str(resolve_records_repo_path(rcfg, data_dir))})` | `rcfg = rcfg.model_copy(update={"repo_path": str(data_dir / "ship-records")})` | P13 |
| M-R1 | `src/probos/__main__.py` | `if promote_first and not _promote_before_reset(config, tier, data_dir, skip_reason, console):` | `if False:` | R1 (no archive). "Promote after delete": the tier loop runs with nothing promoted first |
| M-R2 | `src/probos/__main__.py` | `return False  # AD-1341 S1: a failed promotion refuses the reset` | `return True` | R3 (exit 0, `trust.db` deleted). "Swallow the error" |
| M-R3 | `src/probos/__main__.py` | `timeline_id = _read_instance_id(data_dir)  # before the tier loop deletes it` | `timeline_id = ""` | R1 (exit 1: no instance id). "The instance id read after deletion" |
| M-R4 | `src/probos/__main__.py` | `promote_first = tier >= 2  # AD-1341 S1: tier 1 keeps the crew, so it has nothing to promote` | `promote_first = tier >= 1` | R5 (exit 1 and an archive file). "Tier 1 promotes" |
| M-R5 | `src/probos/__main__.py` | `return _show_promotion_plan(config, data_dir, skip_reason, console)` | `return 0 if _promote_before_reset(config, tier, data_dir, skip_reason, console) else 1` | R6 (the archive file exists). "The dry run writes" |
| M-R6 | `src/probos/__main__.py` | `reset_pidfile = acquire_pidfile(data_dir)` | `reset_pidfile = data_dir / "probos.pid"` | R7 `[soft]` (exit 0; `events.db` deleted; the owner's pidfile unlinked). "The pidfile guard dropped" |
| M-R7 | `src/probos/__main__.py` | `await archive.record_generation(skipped)` | `pass` | R4 (no `generations` row). "A skip without its row" |
| M-R8 | `src/probos/__main__.py` | `return 1  # AD-1341 S1: refused before the tier loop; nothing was deleted` | `return 0` | R3 (exit 0). "A refusal that exits 0" |
| M-R9 | `src/probos/__main__.py` | `if plan.records:  # AD-1341 S1: nothing can be attributed without an instance id` | `if False:` | R9 `[with-records]` (exit 0; deletes) |
| M-R10 | `src/probos/__main__.py` | `if not confirmed and input("  Erase it? [y/N]: ").strip().lower() != "y":` | `if False:` | R10b `[declined]` (the entry is erased) |

**Lines without a row, and why:**
- `ARCHIVE_READER = ""` → `"captain"`, and `read_entry`'s reader argument: **equivalent**. Every record the captain could read beyond the anonymous reader is narrower than ship, and P-R7's gate withholds it. Reading as anonymous is defence in depth (the orchestrator's "read as captain").
- `if not row or int(row[0]) != 1:`: equivalent while `secure_delete` is available.
- `if type(record) is not PromotionRecord:`: A6c kills it only through the database error; not distinct.
- The title and metadata lines in `plan_promotion`: no behaviour reads them in S1.
- The `_valid_reason` call site, the logging lines, and the rest of the `entry_by_id` body: any change breaks A8, or they have no behaviour.
- (A2) `_write_lock`'s construction: K20 to K23 remove each holder. The three `if not self._db:` checks inside the lock are identical lines (no unique row), and a close landing while a write waits for the lock is not stageable without a hook. `_SQLITE_MAX_ROWID`: raised, A16 `[above-sqlite]` fails; lowered, it is equivalent for every id a row can have.
- `_rollback_quietly` and `_close_quietly`: their failure paths are not stageable deterministically.
- (M3) `_skip_promotion_problem`'s two checks and `_cmd_archive`'s disabled, id and reason checks: R4b, R8 and R10b fail on `if False:` for each, and the store's own checks (K14, K15, K18) back them; no extra rows.
- (M3) `_configured_archive_store`'s `mkdir` for the computed default: the tests set `db_path`, and reaching the platform default would write outside `tmp_path`.
- (M3) The pidfile `unlink` in `finally` and its `FileNotFoundError` and `OSError` branches: R1 and R3 assert the file is gone; the failure branch is not stageable deterministically.
- (M3) The notice and summary `console.print` lines: output only.

## 11. Verified Against Codebase (2026-10-22, HEAD `0e122174`, tree `70e8542d8b3b7ae262e91ad147caedfaeb28c9a1`)

Uniqueness: each SEARCH's distinctive line was grepped with no `$` anchor (the working copies are CRLF) and found once, or read in its whole file.

```text
src/probos/knowledge/archive_store.py (190 lines, read whole)
  1-9 docstring "append-only (no updates, no deletes)"   13-19 imports (json, logging, time, dataclass/field, Any, ConnectionFactory)
  24-36 ArchiveEntry (frozen; metadata defaulted last)    39-54 _SCHEMA (archive + 2 indexes)
  57-73 class, __init__, initialize (executescript, commit, log)   81-119 append ("the ONLY write operation")
  143-148 search SQL    161-166 get_recent SQL    174 "SELECT COUNT(*) FROM archive"   178-190 _row_to_entry
src/probos/cognitive/oracle_service.py
  340 archive_store: Any = None  354 self._archive_store  541-551 async def query(query_text, *, agent_id, intent_type, k_per_tier, tiers, ...)
  632-634 archive tier  1134-1157 _query_archive (reads id, timeline_id, category, title, content, author_callsign/agent_type, archived_at)
src/probos/startup/cognitive_services.py
  598-607 records branch: rcfg = config.records; if not rcfg.repo_path: model_copy(... data_dir / "ship-records")
  667-695 archive: resolve_archive_db_path, mkdir only for the default, ArchiveStore(..., connection_factory=default_factory), except -> None
src/probos/config.py
  6 import os; 8 from pathlib import Path; 104-120 imports ArchiveConfig ... RecordsConfig
  2631-2655 resolve_archive_db_path (... return base / "archive.db")   2658 class SensoriumConfig(BaseModel)   3887-3888 records, archive
src/probos/config_models/knowledge.py:317-323 RecordsConfig(enabled, repo_path "" = {data_dir}/ship-records, auto_commit)
src/probos/knowledge/records_store.py
  46-51 _CLASSIFICATION_LEVELS   70 NOTEBOOK_DEFAULT_CLASSIFICATION = "private"   82-153 record_is_readable
  174-186 __init__, repo_path   188-209 initialize (mkdir, git init)   211-226 write_entry(author, path, content, message, *, classification, status, department, topic, tags, metrics, extra_frontmatter, ...)
  324 auto_commit gate   415-448 append_captains_log (author captain, ship, published; captains-log/{date}.md)
  450-508 write_notebook(callsign, topic_slug, content, *, department, tags, classification, metrics, extra_frontmatter)
  930-959 read_entry (reader "captain" unrestricted; private/department gates)   961-1001 list_entries   1027-1047 publish   1190-1200 _parse_document   1202-1213 _safe_path
src/probos/cognitive/dreaming.py:1119 reports/convergence/convergence-{ts}.md; 1129-1136 write_entry(author="system", classification="ship", tags=["convergence","ad-551"])
src/probos/tools/publish_finding_tool.py:691-699 write_notebook(..., classification=written, extra_frontmatter=envelope); 816-827 envelope with claim_id, contest_state
src/probos/__main__.py
  68-75 _default_data_dir -> runtime._platform_data_dir   745-748 _serve acquires the AD-816 pidfile
  2194-2206 rebuild-episodic assert_no_other_instance   2615 _RESET_SUBDIRS   2620-2656 RESET_TIERS
  2883-3077 _cmd_reset (2892-2895 config/data_dir; 2926-2929 dry run; 2932-2935 confirm; 3017-3021 instance id deleted)
  3380-3387 reset parser (--yes, --soft, --full, --dry-run, --wipe-records, --config, --data-dir)   3444-3446 dispatch
src/probos/pidfile_guard.py:109 acquire_pidfile(data_dir)  168 assert_no_other_instance(data_dir)
src/probos/storage/sqlite_factory.py:12-42 SQLiteConnectionFactory.connect(db_path, *, read_only=False); default_factory
src/probos/protocols.py:325-354 DatabaseConnection (execute, executemany, executescript, fetchone, fetchall, commit); 362-371 ConnectionFactory
src/probos/agent_stop.py:150-155 _rollback_quietly (execute("ROLLBACK"))
src/probos/cognitive/episode_archive.py:463-484 secure_delete set+verify; user_version not in (0, V) -> refuse
(A2, read at 67f00845)
src/probos/cognitive/episode_archive.py:451-455 _write_lock = asyncio.Lock() (AD-1340 R3: every mutation and stop() hold it; reads never)   486-490 stop() under it
src/probos/cognitive/procedure_store.py:157-159 _write_lock = asyncio.Lock() (BF-891: binds to the loop on first contention)   cognitive/episodic.py:1466 _store_write_lock
src/probos/knowledge/archive_store.py (M1 as built): 284-289 _rollback_quietly (a connection-wide ROLLBACK); 359-435 the three writes share self._db, unserialised; 419 erase_entry's id guard (type and <= 0 only); 437-443 entry_by_id binds any int
src/probos/storage/sqlite_factory.py:37 aiosqlite.connect (sqlite3's default isolation: an implicit BEGIN before each write)
src/probos/__main__.py (M3 as built): 3309-3318 archive erase (argparse type=int at 3671; only <= 0 refused; a catch-all prints "The erasure failed"); 3328 entry_by_id before 3338 erase_entry
scripts/phantom_api_ast_helper.py:271-274 _PATTERN_B_RE (a line starting "name = ClassName(" or "name=ClassName(" types name contract-wide)
tests/test_issue1419_failed_start_rollback.py:2254 ("_archive_store", "close", "_db", True)
src/probos/infrastructure/backup_inventory.py:216-247 archive root   backup.py:793 src_conn.backup(dest_conn)   config_models/operations.py:585 backup_include_archive_root = True
src/probos/identity.py:103-112 generate_ship_did   ontology/loader.py:95-102 instance id read/strip
src/probos/runtime.py:234-251 _platform_data_dir   doctor/runner.py:32-39 its own _default_data_dir
src/probos/cognitive/self_improvement/versioning.py:129 and cognitive/turn_promotion.py:2264 define promote
docs/development/store-baseline.yaml:121-123 probos.knowledge.archive_store tables [archive]
scripts/check_store_registry.py:50-57 rules; 452-531 detect_tables; 1084-1092 baseline-table-drift
tests/test_ad524_ships_archive.py (186 lines, read whole): 9 import; 23-31 append test; 34-36 no update/delete; 61-77 by category; 100-106 exit_note; 157-175 helper; 178-185 fake
tests/test_issue1419_failed_start_rollback.py:2254 ("_archive_store", "close", "_db", True)
tests/fixtures/ad1343_seam_census.py:25-39 STOP_CALLEES, GUARD_CALLEES, RECORDED; tests/fixtures/ad1343_seam_registry.py:42-61
tests/test_layer_boundaries.py:45-57 knowledge -> {substrate}
pyproject.toml:9 requires-python >=3.12 (StrEnum); 181 asyncio_mode = "auto"; 196 addopts -n 16 --dist=loadfile
```

**A1 additions (2026-10-22; the dry-run tree `0f13771c`, tree `6799dd885f0564c12eaf3613f4bb99834a7269da`, M1 and M2 as this contract builds them).** Each A1 SEARCH was grepped in this contract at `b1a0b80d` with no `$` anchor and found once; each §7.9 to §7.13 SEARCH was read in its file at the lines below.

```text
src/probos/__main__.py
  13 from __future__ import annotations; 19 import asyncio; 25 import sys; 64-65 if TYPE_CHECKING: import httpx; 68 _default_data_dir
  506-509 _load_config_with_fallback -> (load_config(resolved), resolved)
  586 _boot_runtime: data_path = data_dir or _default_data_dir()   675-677 _boot_and_run (no pidfile)
  722-751 _serve: resolved_data_dir = data_dir or _default_data_dir(); acquire_pidfile; AnotherInstanceRunning -> SystemExit(2)
  774, 801, 955 _pidfile.unlink(missing_ok=True)
  2622-2661 RESET_TIERS (no probos.pid), _ALWAYS_PRESERVED   2775-2829 _show_confirmation_prompt   2832-2882 _show_dry_run
  2885-3078 _cmd_reset -> None: 2887 console = Console(); 2894 config; 2896-2897 data_dir; 2904-2905 tier; 2928-2931 dry run;
    2933-2937 confirmation; 2939-3042 tier loop and git commit (3030, 3035 subprocess.run, env=trusted_command_env()); 3044-3078 summary
  3081 _force_remove_readonly   3146-3172 the pairing subparsers (the add_subparsers(dest=..., required=True) pattern)
  3381-3391 reset parser; args = parser.parse_args()   3393-3444 sys.exit(_cmd_*(args)) with a local import sys   3446-3448 reset dispatch
src/probos/pidfile_guard.py: 24-34 AnotherInstanceRunning(RuntimeError); 94-106 O_EXCL create (96 mkdir parents);
  109-165 acquire_pidfile (garbage: unlink and retry; own PID: reclaim; live: raise; stale: unlink and retry); 168-183 assert_no_other_instance
src/probos/knowledge/archive_store.py (built): 71 ARCHIVE_REASON_MAX_CHARS; 94-98 GenerationOutcome; 154-179 GenerationRecord;
  200-223 generations and archive_erasures columns; 313-351 initialize; 393-409 record_generation; 411-435 erase_entry; 437-443 entry_by_id
src/probos/knowledge/archive_promotion.py (built): 86-130 plan_promotion; 133-161 promote_ship_records -> PromotionReport
src/probos/config.py (built): 2631-2655 resolve_archive_db_path; 2658-2666 resolve_records_repo_path; 3897-3899 knowledge, records, archive
src/probos/config_models/knowledge.py: 280-284 KnowledgeConfig.repo_path; 317-322 RecordsConfig; 358-362 ArchiveConfig(enabled, db_path)
src/probos/knowledge/records_store.py:174-176 RecordsStore(config, ontology=None)
src/probos/startup/cognitive_services.py:669-697 the archive at startup (mkdir only for the default)
src/probos/ontology/loader.py:95-102, 153-161 {data_dir}/ontology/instance_id, read and stripped
tests/test_bf892_spawn_env_guard.py:82-85 TRUSTED_ENV_SITES ("src/probos/__main__.py", "_cmd_reset"): (2, ...)
tests/test_quality_hardening.py:64-71 "text=True" not in getsource(_cmd_reset)
tests/test_ad1340_s1_restore_reset.py:44 imports _run_reset; 264-297 tiers 2 and 1; 318-332 two EpisodicMemory constructions in __main__
tests/test_bf902_fts_reconciliation.py:32 imports _run_reset; 242 and 259 async; 280-292 RESET_TIERS pins
tests/test_reset_integration.py:35-57 _reset_args, _run_reset (MagicMock config)
tests/test_distribution.py:10-16 imports; 1099-1288 seven reset tests, six at tier 2 or above
tests/test_proactive.py:698-755 two tier 2+ tests; 760-811 two tier 1 tests
tests/test_identity_deterministic.py:3-6 imports; 117-180 three tier 2 tests
tests/test_dotenv.py:12-40 main() with --help builds the whole parser
tests/test_ad1270e1_config_facade.py:1515-1556, 1780-1791 the pinned counts
docs/development/config-facade-baseline.yaml:48-55 surface_counts; 142 names:; 445-449 the rows around resolve_archive_db_path
tests/fixtures/ad1343_seam_census.py:25-39; tests/fixtures/ad1343_seam_registry.py:42-61
scripts/phantom-api-precheck.ps1:113-128 (only python fences kept, SEARCH blocks included), 217, 228; scripts/phantom_api_ast_helper.py:271-274 pattern B
```

## Absence Verified (2026-10-22)

```text
CLAIM: nothing in src calls an ArchiveStore write
RUN:   Grep 'archive_store\.[a-z_]+\(' src/probos
FOUND: oracle_service.py:1138 search; cognitive_services.py:687 initialize; shutdown.py:2019 close
HOLDS: yes

CLAIM: none of the new names exist yet
RUN:   Grep '\.(promote_entry|erase_entry|record_generation|entry_by_id|plan_promotion|promote_ship_records|source_kind_for)\b|resolve_records_repo_path|archive_promotion' *.py
FOUND: 0
HOLDS: yes

CLAIM: ArchiveEntry is built only by the store and test_ad524
RUN:   Grep 'ArchiveEntry|knowledge\.archive_store' *.py
FOUND: archive_store.py:25,127,156,179-180; cognitive_services.py:672; test_ad524_ships_archive.py:9,123,179,183
HOLDS: yes

CLAIM: no production caller of RecordsStore.publish
RUN:   Grep '\.publish\(' src/probos
FOUND: workspace_result_store.py:1093 (artifacts), federation/envelope.py:386, mesh/nats_bus.py (4)
HOLDS: yes: PUBLISHED_REPORT and a published notebook have no live producer today; the API's own callers are served

CLAIM: _cmd_reset has no running-vessel guard
RUN:   Read __main__.py:2883-3077
FOUND: no pidfile, acquire or assert_no_other_instance
HOLDS: yes

CLAIM: procedures/ is in no reset tier
RUN:   Read __main__.py:2615, 2620-2656, 3001-3021
FOUND: tier dirs checkpoints, semantic, ship-records, scout_reports; specials: UUID-named dirs, knowledge subdirs, instance_id
HOLDS: yes

CLAIM: no new name is an AD-1343 census callee
RUN:   Read ad1343_seam_census.py:25-39 and ad1343_seam_registry.py:42-61
FOUND: none of promote_entry, record_generation, erase_entry, entry_by_id, plan_promotion, promote_ship_records, source_kind_for
HOLDS: yes
```

**A1 additions:**

```text
CLAIM: only `probos serve` holds the AD-816 pidfile; the interactive shell takes none                    (A1-AV1)
RUN:   Grep 'acquire_pidfile|assert_no_other_instance' src/probos
FOUND: pidfile_guard.py:109, 168, 171; __main__.py:745, 748 (_serve); 2105, 2110 (backup-reclaim --force probe); 2198, 2208 (rebuild-episodic probe)
HOLDS: yes: _boot_and_run acquires nothing (register RA1-1)

CLAIM: no caller reads `_cmd_reset`'s return value                                                         (A1-AV2)
RUN:   Grep '_cmd_reset' *.py
FOUND: __main__.py:2885 (def), 3447 (dispatch, value dropped); test_bf892:85 (site key); test_distribution.py:1110-1288 (7 calls);
       test_identity_deterministic.py:125-180 (3); test_proactive.py:702-809 (4); test_quality_hardening.py:68-70 (getsource); test_reset_integration.py:46, 57
HOLDS: yes: no assignment, assert or comparison

CLAIM: only bf902's two async tests call `_cmd_reset` inside a running event loop                           (A1-AV3)
RUN:   Grep '^(async )?def test_|_run_reset\(' in test_ad1340_s1_restore_reset.py, test_bf902_fts_reconciliation.py; Grep 'async def' in the four updated files
FOUND: bf902:242 (tier 2), :259 (tier 1) async; ad1340:264 sync; the reset tests in the four files are sync defs
HOLDS: yes: with the archive disabled (7.10), neither reaches asyncio.run

CLAIM: no M3 name is an AD-1343 census callee                                                               (A1-AV4)
RUN:   Read tests/fixtures/ad1343_seam_census.py:25-39 and ad1343_seam_registry.py:42-61
FOUND: none of _cmd_archive, _erase_archive_entry, _promote_before_reset, _promote_into_archive, _show_promotion_plan, _read_instance_id,
       _reset_records_store, _configured_archive_store, _skip_promotion_problem, acquire_pidfile, record_generation, erase_entry, entry_by_id,
       plan_promotion, promote_ship_records, run
HOLDS: yes

CLAIM: nothing in src names erase_entry, record_generation or entry_by_id as an attribute today            (A1-AV5)
RUN:   Grep '\.(erase_entry|record_generation|entry_by_id)\b' src/probos
FOUND: 0
HOLDS: yes: R11 fails on the M2 tree and passes after 7.9

CLAIM: no reset tier deletes the pidfile                                                                    (A1-AV6)
RUN:   Read __main__.py:2622-2661; Grep 'probos\.pid' src/probos
FOUND: no probos.pid in RESET_TIERS; pidfile_guard.py:3, 116, 174 (the other hits are the module name)
HOLDS: yes

CLAIM: no test pins the CLI's subcommands or calls main() with reset; no archive subcommand exists         (A1-AV7)
RUN:   Grep '"reset"|add_parser\("archive"' {src,tests}/**/*.py; Grep '"backup-reclaim"|_choices_actions' tests
FOUND: __main__.py:3382 (the reset parser), 2974 (an audit literal); no archive parser; test_dotenv.py calls main() with --help only
HOLDS: yes

CLAIM: the facade counts are pinned only in the baseline and four test lines                               (A1-AV8)
RUN:   Grep 'names=30[0-9]|== 307|== 294' over tests, scripts, docs, src
FOUND: test_ad1270e1_config_facade.py:1521, 1522, 1555, 1791; config-facade-baseline.yaml:54-55; test_bf822_browser_navigation_floor.py:937, 1106, 1354 (HTTP 307, unrelated)
HOLDS: yes

CLAIM: no store method calls another store method, so the non-re-entrant lock cannot deadlock             (A2-AV1)
RUN:   Grep 'self\.(promote_entry|record_generation|erase_entry|entry_by_id|search|get_recent|count|close|initialize)\(' src/probos/knowledge/archive_store.py (at 67f00845)
FOUND: 0
HOLDS: yes

CLAIM: no src caller overlaps two calls on one archive store (F1 is injected-only in S1)                   (A2-AV2)
RUN:   Grep '\.(promote_entry|record_generation|erase_entry|entry_by_id)\(' src/probos; Grep 'gather|create_task|TaskGroup' src/probos/knowledge/archive_promotion.py
FOUND: archive_promotion.py:147; __main__.py:3239, 3247, 3328, 3338, each awaited alone; 0 in archive_promotion.py
HOLDS: yes. S2 to S6 add writers inside the vessel, which is why D16 fixes it now

CLAIM: M1's tests had no overlapping-write or failed-write coverage                                         (A2-AV3)
RUN:   Grep 'gather|create_task|asyncio' tests/test_ad1341_s1_archive_store.py (at 67f00845)
FOUND: 0
HOLDS: yes: A14, A14b and A15 are new
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 3 (`Name(`) | The capitalised calls are ProbOS symbols (`ArchiveStore`, `OracleService`, `RecordsStore`, `RecordsConfig`, `ArchiveEntry`) or classes this contract defines (`SourceKind`, `PromotionOutcome`, `GenerationOutcome`, `PromotionRecord`, `GenerationRecord`, `PromotionPlan`, `PromotionReport`). The exception classes appear only in `raise` and `except` lines. No SQL function is spelled as `NAME(`: there is no `COUNT(` in a block, and the SQL uses `EXISTS (` and `CONFLICT (` with a space. `PurePosixPath` is avoided (`rsplit`/`removesuffix`) |
| Pattern 2 (`Name.attr`) | Lower-case attributes on capitalised receivers: `ArchiveStore.promote_entry` and `RecordsStore.read_entry` are defined here or exist. Enum members are upper-case |
| Field and keyword check | `RecordsConfig(repo_path, auto_commit)`, `OracleService(archive_store)`, the `write_entry`, `write_notebook` and `query` keywords all exist. `ArchiveEntry`'s new fields are added in the middle of the call (7.1 pair 8), so no whole new `ArchiveEntry(...)` call appears |
| Method check (pattern B) | No `x = ArchiveStore(...)` assignment precedes a new-method call; stores come from `_store`/`_archive` helpers |
| Layer | `archive_promotion.py` imports only `probos.knowledge.*` (P14; `test_layer_boundaries.py`) |
| Store registry | Rule 11: 7.3 updates the row; run `scripts/check_store_registry.py --check` in M1 |
| `.db` literal census (`test_ad1265_backup_coverage.py`) | no new `*.db` literal in `src` |
| AD-1343 census | no new name in `STOP_CALLEES`, `GUARD_CALLEES` or `RECORDED`; no `.complete(`, `.finalize(` or `.report(` call |
| Subprocess census (`test_bf892`) | none added. M3 re-indents the tier loop inside `_cmd_reset`'s `try` instead of extracting it, so both git launches keep the site key `("src/probos/__main__.py", "_cmd_reset")` (`test_bf892_spawn_env_guard.py:85`) |
| Hidden pins | `test_ad524` (7.2); `test_issue1419:2254` (`close` and `_db` kept); `test_quality_hardening.py:64-71` (no `text=True` added to `_cmd_reset`); `test_ad1340_s1_restore_reset.py:325-327` (no `EpisodicMemory` construction added to `__main__`); the `RESET_TIERS` pins (`test_ad1340_s1_restore_reset.py:293-296`, `test_bf902_fts_reconciliation.py:282-292`: unchanged); `test_bf877_unapproved_design_is_refused.py:457` (the `ProbOSShell` sites unchanged); `test_bf781_isolation_claims.py:378-385` (the `wait_for` timeouts unchanged); the facade counts (7.6c) |
| db-connect | the store uses its injected `ConnectionFactory`; tests use `sqlite3` read-back only |
| Config | no new field; `resolve_records_repo_path` reads no environment variable. It is a new public name of `probos.config`: 7.6b adds its `tier: owned` row beside `resolve_archive_db_path` (AD-1265's precedent) and the counts 308 and 295, and 7.6c updates the four pinned values. M2's gate runs `scripts/check_config_facade.py --check`. No mutation row: the baseline is data, guarded by `--check` and the two pinned tests |
| Size | `archive_store.py` grows by about 245 lines (to about 435); `archive_promotion.py` about 150; the tests about 440 and 300 |
| Ledger | M4 |
| Phantom precheck (M3) | the new capitalised calls are ProbOS classes (`GenerationRecord`, `ArchiveStore`, `RecordsStore`; in the test also `SystemConfig`, `KnowledgeConfig`, `ArchiveConfig`, `RecordsConfig`, `OracleService`). The test aliases `argparse.Namespace` as `_Namespace`; 7.11 and 7.13 alias `SimpleNamespace` as `_SimpleNamespace`. No python block includes the existing `Console` construction (`__main__.py:2887`) or a fake's `SimpleNamespace` constructor line, and `_cmd_archive` writes with `print`. `AnotherInstanceRunning` appears only in `except` |
| Method check (pattern B, M3) | no store is assigned from a constructor: both come from `return` helpers (`_configured_archive_store`, `_reset_records_store`; in the test `_archive_store`, `_records`). `skipped` and `closed` (built from `GenerationRecord`) get no method call |
| AD-1343 census (M3) | no new name in `STOP_CALLEES`, `GUARD_CALLEES` or `RECORDED` (A1-AV4); no `.report(`, `.complete(` or `.finalize(` call |
| Event loop (M3) | `_cmd_reset` runs at most one `asyncio.run`, after the archive-enabled check; the async callers (A1-AV3) reach it with the archive disabled or at tier 1 |
| Lock (A2) | the lock comes from `asyncio`; `src` annotates `asyncio.Lock` (`http_fetch.py:782`), so the precheck resolves it, and it binds to the running loop only when first contended (BF-891, `procedure_store.py:157-159`). No new name in `STOP_CALLEES`, `GUARD_CALLEES`, `RECORDED` or `AGENT_WORK_METHODS`; no new public method (A7 unchanged) |
| Phantom precheck (A2) | 20 candidates on the A1 text, 0 after A2: 7.14's `_config` binds `section` (no method is called on it anywhere), so no line begins `archive=`; the reset's `finally` calls `unlink()` and passes on `FileNotFoundError`. A15's trigger spells `RAISE (` with a space |
| Size (M3) | `__main__.py` grows by about 250 lines; the new test is about 330 lines |

## 13. Prior Art and Blind Spots

**Internal work used:**
- AD-524 (the archive this completes).
- AD-1340: `secure_delete` set and verified, and the `user_version` refusal (`episode_archive.py:463-484`). Adopted.
- AD-1343: `_rollback_quietly` (`agent_stop.py:150-155`). Adopted.
- AD-754: the erasure right. Extended.
- BF-679: the reader rule. Used as defence in depth.
- AD-1140: `claim_id` as the governed-finding marker. Used as the criterion.
- AD-551: convergence reports.
- AD-816: the pidfile (M3).
- AD-1265 (the backup root) and AD-1256 (the registry baseline).
- `docs/research/`: only `tiered-trust-initialization-research.md` and `harness2-absorption.md` mention "generational", and neither is about knowledge persistence. Considered, nothing to absorb.

**External prior art** (date used for overdue rows: 2026-10-22):
- SQLite UPSERT documentation: the conflict target, and the rule that `INSERT … SELECT … ON CONFLICT` needs a `WHERE`. Adopted in `_PROMOTE_SQL`. <https://www.sqlite.org/lang_upsert.html>
- SQLite PRAGMA documentation: `secure_delete` overwrites deleted content with zeros; `user_version` lives in the file header. Adopted. <https://www.sqlite.org/pragma.html>
- Erasure practice:
  - an erasure-fact row written in the same transaction as the delete: adopted (D7);
  - tombstones do not reach backups: disclosed, as AD-1340 did;
  - free-text reasons can re-identify: considered and rejected for parity, with a help-text mitigation in M3.

  Sources: <https://gravitee.io/corpus/gen-1808/data-erasure/event-tombstones-and-gdpr-erasure.html>, <https://www.tdcommons.org/dpubs_series/10873>, <https://appmaster.io/blog/privacy-deletion-audit-compromise-patterns>
- Memvid (overdue, last reviewed 2026-04-05): examined. It stores memory as append-only immutable frames with per-frame checksums, which matches the content-hash key; nothing new. <https://yuv.ai/blog/memvid-ai-agent-memory-in-a-single-portable-file>
- AI Meets Brain survey (overdue, last reviewed 2026-04-12): considered and deferred to S4/S5 (consolidation).

**Blind spots found:**
1. Records survive tier 2, so they would be re-promoted every reset. Fixed by D3.
2. An erasure would be undone by the next promotion. Fixed by D7.
3. Backups keep erased bytes. Disclosed.
4. An AD-1266 restore resurrects erased entries. Register.
5. An overridden records path survives `--full`. Register.
6. Several vessels on one machine share the archive. Accepted; disclosed effect 7.
7. Records carry no author DID, so `author_did` is empty until S4.
8. The doctor's data-dir function differs from the reset's. Register.
9. (A1) Only `probos serve` takes the pidfile; the interactive shell does not. Register RA1-1.
10. (A1) Two async tests call `_cmd_reset` inside a running loop. Fixed: the disabled check comes before `asyncio.run`.
11. (A1) Two resets with no boot between have no instance id. Disclosed effect 8; register RA1-2.
12. (A1) The config facade pins its public-name counts. Fixed by 7.6b and 7.6c.
13. (A1) Captain-supplied and archive text printed through Rich markup. `escape` on `_cmd_reset`'s new output (BF-903 A3's pattern); plain `print` in `_cmd_archive`.
14. (A2) Overlapping calls share one connection: one call's rollback undid another's work, which still reported success. Fixed by D16.
15. (A2) An id above SQLite's INTEGER range raised instead of meaning "no entry", and the CLI reaches it with the Captain's input. Fixed by D17.
16. (A2) A read during a write sees the write in flight (one connection). Accepted: no S1 process reads and writes one store at once. Register RA2-1.
17. (A2) Two concurrent `initialize` calls each open a connection (AD-524's shape, unchanged). Register RA2-2.

**A1 prior art.** AD-816's `acquire_pidfile` is reused, not reimplemented. `verify-snapshot`'s pidfile-free read path is followed for `--dry-run`. BF-903 A3's `rich.markup.escape` is adopted. External search was skipped: this is ProbOS CLI plumbing with no outside analogue worth the search.

**A2 prior art.** AD-1340 R3's `_write_lock` (`episode_archive.py:451-455`) is followed: created in `__init__`, held by every mutation and the close, never by reads; `procedure_store.py:159` (BF-891) and `episodic.py:1466` create theirs the same way. AD-1340's `stop()` swaps the handle out and swallows a failed close; this store keeps its own close, which keeps `_db` after a failure for shutdown's last resort (`test_issue1419_failed_start_rollback.py:2254`). External search was skipped: the defect is this store sharing its own connection, and the repo's pattern fixes it; the reference-projects review does not apply to a bug-fix amendment.

## 14. Diff Reviewer: properties to verify

1. No production path writes the archive except `promote_entry`, and `src` names `promote_entry` only in `knowledge/archive_promotion.py` (P15). `append` is gone.
2. A record narrower than `ship`, with a non-`SourceKind` kind, or with blank required text cannot be built. The service withholds such records rather than failing the run. No `SourceKind` member names an episode.
3. The idempotence key is `(source_kind, source_ref, content_sha256)` in both the index and the conflict target (one constant). A second run, under any timeline, writes nothing.
4. The erasure check and the insert are one statement. An erased source (kind and ref) is never written again, with any content.
5. `erase_entry` writes the marker and deletes the row in one transaction; the marker has exactly the 7 columns in A8 and no title, content, metadata or hash. A missing id, including one above SQLite's largest rowid (D17), writes nothing and returns False; `entry_by_id` returns None for it. A failure rolls back.
5b. (A2) `promote_entry`, `record_generation`, `erase_entry` and `close` each hold the one `_write_lock` (created in `__init__`) from the `_db` check through the commit or rollback; reads and `initialize` do not. No method holding it calls another store method. `close` still clears `_db` only after a successful close. A14, A14b and A15 read the file back with `sqlite3`, and each fails on the unamended M1.
6. `initialize` sets and verifies `secure_delete` before any schema work, refuses any version but 0 or 1 unopened, adds only absent columns, creates the partial unique index, and writes `user_version` last. A failed open closes the connection.
7. v0 rows survive with their content; `search`, `get_recent` and the Oracle return them.
8. Startup's records path is byte-identical to before; the resolver has no other effect.
9. The service makes no model call, swallows nothing, reads as `""`, and writes nothing while planning.
10. The store-baseline row lists exactly the tables the module creates, sorted.
11. Each updated test changes only where it pinned `append`, with an inline `AD-1341 S1 (#1569)` reason; none is deleted.
12. (M3) At tier 2 and above nothing is deleted before `_promote_before_reset` returns True. Any exception, a refused archive version, or records with no instance id exit 1 with every file in place. Tier 1 never reads `config.archive`.
13. (M3) Every executing reset (`--soft` included) holds `{data_dir}/probos.pid` from after the confirmation through the tier loop and the git commit, and releases it on every exit. A live owner exits 1 and its pidfile is untouched. `--dry-run` takes no pidfile and opens no archive.
14. (M3) A blank, over-long or tier 1 `--skip-promotion` exits 2 before anything is read, locked or deleted. A valid one writes exactly one `skipped` row and promotes nothing.
15. (M3) The instance id is read before the tier loop, and the `promoted` row names it.
16. (M3) `probos archive erase` shows the entry and asks unless `--yes`. It exits 2 with the archive disabled or a bad id or reason, 1 for no such entry, and 0 when erased or declined. `src` names `erase_entry` and `record_generation` only in `__main__.py` (R11).
17. (M3) The tier loop and git commit are byte-identical apart from four spaces of indentation. `RESET_TIERS`, both launches and their `trusted_command_env()` are unchanged.
18. (M2, M3) The fakes disable the archive with an inline `AD-1341 S1 (#1569)` reason, and none is deleted. The facade counts move only by the one owned name.

## 15. Acceptance criteria

1. Schema v1 with provenance, migrated in place, versions refused, `secure_delete` verified (A1–A3; K3–K7).
2. One idempotent write, D3's key, C1 enforced at the store, a closed `SourceKind` with no episode member (A4–A7; K1, K2, K8, K16, K17, K19).
3. The Captain's erasure: the row gone, the bytes overwritten, a content-free marker, no re-promotion, and an id beyond SQLite is no entry (A8–A11, A16; K9–K15, K24, K25).
4. Generations recorded with validation (A12; K18).
4b. (A2) One transaction at a time on the store's one connection: overlapping writes, a failed write and a close never undo or end another call's work (D16; A14, A14b, A15; K20–K23).
5. Records-only promotion with fixed criteria, the anonymous reader, C1 withholding, offline reads, no swallowed failure, and the chain to a later crew's Oracle (P1–P11; P-R1–P-R8).
6. One records-path resolver (P12, P13; C-R1, C-R2, S-R1); layer and census (P14, P15); the config facade baseline and its pins name it (7.6b, 7.6c; `check_config_facade.py --check`).
7. (M3) `probos reset` promotes before it deletes at tier 2 and above. It refuses with nothing deleted on any failure, with no instance id for records to promote, or beside a live pidfile. It records `--skip-promotion`, and lists the plan on `--dry-run` without writing. `probos archive erase` is the Captain's erasure, and an erased source stays out of the next generation's archive (R1–R13; M-R1–M-R10).
8. Every change has a test that fails on today's tree (§6), and every mutation row is killed by the named test. One broad gate and one PR for M1–M4; a cross-family GPT-6.1 Sol review per milestone (tier HIGH).
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
