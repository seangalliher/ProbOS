# AD-1341 S1: knowledge the crew published is promoted into the Ship's Archive before a reset, with provenance, and the Captain can erase an archive entry

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** M1 and M2 are build-ready. M3 (the CLI and reset integration) follows as Amendment A1, specified in §4; M4 is §8. Slice 1 of 6 of #1569; it does not close the issue. **Tier HIGH** (the archive, an erasure, data integrity). No new AD or BF number. **Base:** `origin/main` `0e122174`, tree `70e8542d8b3b7ae262e91ad147caedfaeb28c9a1`. BF-903 merges first; it touches only `__main__.py`'s pairing CLI and the trackers, so M3 and §8 re-anchor on text. **Source:** the Architect's consults `98e0fdbf` (2026-10-18) and this one.

**Tests:** M1 `tests/test_ad1341_s1_archive_store.py`: 16 functions, 40 cases. M2 `tests/test_ad1341_s1_promotion.py`: 16 functions, 34 cases. Updated where they pinned the old write: `tests/test_ad524_ships_archive.py` (3 tests and its helper, M1). M3's tests are in Amendment A1.

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
  - **(A) chosen:** every executing `probos reset` (`--soft` included) acquires the AD-816 pidfile after confirmation and releases it when done; a live owner means refuse, exit 1, nothing touched. It protects against a promotion reading records mid-write, deletions racing a live writer (a locked file on Windows leaves a partial reset), and a vessel booting mid-reset and creating a new instance id. `--dry-run` takes no pidfile, following `verify-snapshot`.
  - (B) `assert_no_other_instance`: rejected. It only probes, so a vessel could start right after the check.
  - (C) warn: rejected. The command deletes.
- **D13 (archive disabled, M3).** With `archive.enabled` False there is nowhere to promote to. The reset prints a notice and proceeds; this is configuration, not a failure. `probos archive erase` refuses with exit code 2.
- **D14 (tier).** HIGH.
- **D15 (the Captain).** Nothing in S1 requires the Captain; C1 is applied as decided.

**Disclosed effects.**
1. The live archive migrates to v1 on the first boot after merge (0 rows, additive).
2. An archive at another schema version is refused at boot; the Oracle's archive tier is off, with the existing warning.
3. (M3) `probos reset` at tier 2 or above promotes first and refuses on failure, exiting 1 (it always exited 0 before). `--skip-promotion REASON` is recorded.
4. (M3) Every executing reset refuses while a vessel owns the data directory.
5. Erased bytes stay in earlier AD-1265 snapshots until they age out (as in AD-1340).
6. A record written in one generation but first eligible in a later one is attributed to the later timeline.
7. Two ships sharing the default archive path keep one entry for identical content at the same records path, under whichever ship promoted it first.

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate at `-n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Files (§7) | Focused gate |
|---|---|---|
| **M1** store | 7.1 `knowledge/archive_store.py`; 7.2 `tests/test_ad524_ships_archive.py`; 7.3 `docs/development/store-baseline.yaml`; 7.4 new test | `tests/test_ad1341_s1_archive_store.py tests/test_ad524_ships_archive.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1256_store_registry.py tests/test_ad1265_backup_coverage.py tests/test_layer_boundaries.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` |
| **M2** service | 7.5 `config.py`; 7.6 `startup/cognitive_services.py`; 7.7 new `knowledge/archive_promotion.py`; 7.8 new test | `tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_archive_store.py tests/test_records_store.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf084_truncation_and_manuals.py tests/test_ad1270e1_config_facade.py tests/test_layer_boundaries.py tests/test_ad1265_backup_coverage.py tests/test_ad1256_store_registry.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py` |
| **M3** CLI and reset | Amendment A1 (spec below) | see below |
| **M4** trackers | §8 | `tests/test_ad1184_ad_ledger.py`; `scripts/gen_ad_ledger.py --check` |

If a test outside §7 fails only because it called `ArchiveStore.append`, update it to `promote_entry` with an inline `AD-1341 S1 (#1569)` reason; never delete it. Stop and report any other failure.

### M3 specification (to be written as Amendment A1, pairs `### 7.9` onward, inserted before §8)

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
| `archive.db` schema v1 | the AD-1265 backup root (online backup copies every table); AD-524 code after a revert (its statements name only v0 columns; NULL hashes sit outside the partial index) | additive |
| `store-baseline.yaml` row | `scripts/check_store_registry.py --check`; `tests/test_ad1256_store_registry.py` | row matches the tree |
| `resolve_records_repo_path` | startup's records branch (7.6); M3's reset | the startup branch behaves identically |
| `plan_promotion`, `promote_ship_records`, `source_kind_for`, `ARCHIVE_READER` | M3 | new |

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

Updated pins, not new cases: 7.2.

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

Pair 4 of 8: the class docstring and `initialize`.

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
```
REPLACE:
```python
class ArchiveStore:
    """The Ship's Archive (AD-524), with AD-1341's provenance, promotion and the Captain's erasure.

    Agents and services never update or delete an entry: ``promote_entry`` is the one write and
    ``erase_entry`` the one removal (Captain-only, through ``probos archive erase``). Uses the
    ConnectionFactory protocol for cloud-ready storage.
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None

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
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")
        kind = record.source_kind.value
        params = (
            record.timeline_id, kind, record.title, record.content, record.author_agent_type,
            record.author_callsign, time.time(), json.dumps(record.metadata), kind, record.source_ref,
            record.content_sha256, record.classification, record.author_did,
            json.dumps(list(record.source_episode_ids)), kind, record.source_ref,
        )
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
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")
        params = (
            closure.timeline_id, closure.reset_tier, closure.outcome.value, closure.created, closure.present,
            closure.erased, closure.withheld, closure.reason.strip(), time.time(),
        )
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
        again. Returns False, writing nothing, when no entry has this id.
        """
        if type(entry_id) is not int or entry_id <= 0:
            raise ValueError("AD-1341: an archive entry id is a positive integer")
        text = _valid_reason(reason)
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")
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
        """AD-1341: one entry, so the erasure can show the Captain what it is about to remove."""
        if not self._db:
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

**AD-1341 S1 (2026-10-22), #1569 slice 1 of 6 -- what the crew published survives a reset: `probos reset` promotes it into the Ship's Archive first, with provenance, and the Captain can erase an archive entry.** The Ship's Archive (AD-524) is at schema v1, migrated in place from v0. It gains provenance columns (source kind and ref, content SHA-256, classification, author DID, source episode ids), a partial unique index on `(source_kind, source_ref, content_sha256)`, and `generations` and `archive_erasures` tables; `secure_delete` is set and verified, and any other schema version is refused. `ArchiveStore.append` is gone. `promote_entry(PromotionRecord)` is the one write: idempotent across timelines, because Ship's Records survive a tier 2 reset. Only `ship` and `fleet` records can be built (C1). There is no episode source kind. `erase_entry` deletes a row and leaves a marker with no title, content or hash, which also keeps that source from being promoted again. The records-only service `knowledge/archive_promotion.py` promotes convergence reports, the Captain's log, published reports and governed notebook findings, read as the anonymous reader, with no model call; anything narrower than ship is withheld and reported. `config.resolve_records_repo_path` is the one records-path resolver. `probos reset` at tier 2 and above promotes before it wipes and refuses on any failure (exit 1). `--skip-promotion REASON` is recorded in `generations`, `--dry-run` lists the plan, and every executing reset holds the AD-816 pidfile and refuses beside a running vessel. `probos archive erase ENTRY_ID --reason` is the Captain's erasure. New: `tests/test_ad1341_s1_archive_store.py`, `tests/test_ad1341_s1_promotion.py` and `tests/test_ad1341_s1_reset_and_erase.py` (the real store, records, Oracle and reset command). Updated where they pinned the old write or used partial config fakes: `test_ad524_ships_archive.py`, `test_reset_integration.py`, `test_distribution.py`, `test_proactive.py` and `test_identity_deterministic.py`. The store-registry baseline row lists the two new tables. The contract is `prompts/ad-1341-s1-archive-provenance-promotion.md`.

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

- *Scope.* Slice 1 of #1569, in four milestone commits, one gate and one PR. Files: `knowledge/archive_store.py` (schema v1, `promote_entry`, `record_generation`, `erase_entry`, `entry_by_id`, the record types), new `knowledge/archive_promotion.py`, `config.py` (`resolve_records_repo_path`), `startup/cognitive_services.py`, `__main__.py` (`probos reset` promotion, `probos archive erase`), `docs/development/store-baseline.yaml` and tests. Contract: `prompts/ad-1341-s1-archive-provenance-promotion.md`. Later slices: S2 the inherited label, S3 the review queue and veto, S4 lessons and the stand-down, S5 after-action triggers and continuous promotion, S6 the `--full` snapshot and clean slate.
- *D3 (the key).* `(source_kind, source_ref, content_sha256)`, without the timeline. Ship's Records survive a tier 2 reset, so a key with the timeline would archive every surviving record again under each new timeline: false provenance, duplicates, and an erasure undone. A changed document is a new entry under the timeline that changed it.
- *D4-D6 (the store).* `promote_entry` is the one write (`append` is removed; `promote` was already a method name on two other classes); the erasure check and the insert are one statement. The contract types live in the store module and validate on construction with exact types; nothing narrower than `ship` can be built (C1). The migration is additive and idempotent, and `user_version` is written last; any other version is refused; `secure_delete` is verified.
- *D7 (erasure).* The marker holds the entry id, timeline, source kind and ref, the reason and the time; never the title, content, metadata or hash. It blocks re-promotion of that source with any content, because the source still exists in Ship's Records.
- *D8 (criteria).* Convergence reports by `system`, the Captain's log by `captain`, other reports when `published`, notebooks with a `claim_id` (AD-1140) or `published`. Read as the anonymous reader; anything narrower than ship, or with an empty body, is withheld and reported. No model call; records carry no episode ids.
- *D11 (store registry).* The baseline row is updated, not declared: the archive lives outside `data_dir`, so its declaration is AD-1265's second-root question.
- *D12-D13 (the reset).* At tier 2 and above `probos reset` promotes before deleting and refuses on any failure (exit 1). `--skip-promotion REASON` writes a `generations` row. Every executing reset holds the AD-816 pidfile, so it refuses beside a running vessel. With the archive disabled it proceeds with a notice.
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
- Federation sharing of the archive; trust scoring (the just-culture note goes to its next owner).

## 10. Mutation rows (30 rows for M1 and M2; whole stripped lines, each occurring once in its file after §7)

Tier HIGH: every changed production file has rows. Run each row against `tests/test_ad1341_s1_archive_store.py` (rows K) or `tests/test_ad1341_s1_promotion.py` (rows P, C, S) on the contract-applied tree, after an unmutated baseline run that passes. Restore each file before the next row. M3's rows come with Amendment A1.

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

**Lines without a row, and why:**
- `ARCHIVE_READER = ""` → `"captain"`, and `read_entry`'s reader argument: **equivalent**. Every record the captain could read beyond the anonymous reader is narrower than ship, and P-R7's gate withholds it. Reading as anonymous is defence in depth (the orchestrator's "read as captain").
- `if not row or int(row[0]) != 1:`: equivalent while `secure_delete` is available.
- `if type(record) is not PromotionRecord:`: A6c kills it only through the database error; not distinct.
- The title and metadata lines in `plan_promotion`: no behaviour reads them in S1.
- The `_valid_reason` call site, the logging lines, and the `entry_by_id` body: any change breaks A8, or they have no behaviour.
- `_rollback_quietly` and `_close_quietly`: their failure paths are not stageable deterministically.

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
| Subprocess census (`test_bf892`) | none added (M1, M2); M3 must add none to `_cmd_reset` |
| Hidden pins | `test_ad524` (7.2); `test_issue1419:2254` (`close` and `_db` kept); M3's `_cmd_reset` and `RESET_TIERS` pins (§4) |
| db-connect | the store uses its injected `ConnectionFactory`; tests use `sqlite3` read-back only |
| Config | no new field; `resolve_records_repo_path` reads no environment variable (`test_ad1270e1_config_facade.py` in M2) |
| Size | `archive_store.py` grows by about 230 lines (to about 420); `archive_promotion.py` about 150; the tests about 330 and 300 |
| Ledger | M4 |

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

## 14. Diff Reviewer: properties to verify

1. No production path writes the archive except `promote_entry`, and `src` names `promote_entry` only in `knowledge/archive_promotion.py` (P15). `append` is gone.
2. A record narrower than `ship`, with a non-`SourceKind` kind, or with blank required text cannot be built. The service withholds such records rather than failing the run. No `SourceKind` member names an episode.
3. The idempotence key is `(source_kind, source_ref, content_sha256)` in both the index and the conflict target (one constant). A second run, under any timeline, writes nothing.
4. The erasure check and the insert are one statement. An erased source (kind and ref) is never written again, with any content.
5. `erase_entry` writes the marker and deletes the row in one transaction; the marker has exactly the 7 columns in A8 and no title, content, metadata or hash. A missing id writes nothing and returns False. A failure rolls back.
6. `initialize` sets and verifies `secure_delete` before any schema work, refuses any version but 0 or 1 unopened, adds only absent columns, creates the partial unique index, and writes `user_version` last. A failed open closes the connection.
7. v0 rows survive with their content; `search`, `get_recent` and the Oracle return them.
8. Startup's records path is byte-identical to before; the resolver has no other effect.
9. The service makes no model call, swallows nothing, reads as `""`, and writes nothing while planning.
10. The store-baseline row lists exactly the tables the module creates, sorted.
11. Each updated test changes only where it pinned `append`, with an inline `AD-1341 S1 (#1569)` reason; none is deleted.

## 15. Acceptance criteria

1. Schema v1 with provenance, migrated in place, versions refused, `secure_delete` verified (A1–A3; K3–K7).
2. One idempotent write, D3's key, C1 enforced at the store, a closed `SourceKind` with no episode member (A4–A7; K1, K2, K8, K16, K17, K19).
3. The Captain's erasure: the row gone, the bytes overwritten, a content-free marker, no re-promotion (A8–A11; K9–K15).
4. Generations recorded with validation (A12; K18).
5. Records-only promotion with fixed criteria, the anonymous reader, C1 withholding, offline reads, no swallowed failure, and the chain to a later crew's Oracle (P1–P11; P-R1–P-R8).
6. One records-path resolver (P12, P13; C-R1, C-R2, S-R1); layer and census (P14, P15).
7. Every change has a test that fails on today's tree (§6), and every mutation row is killed by the named test. One broad gate and one PR for M1–M4; a cross-family GPT-6.1 Sol review per milestone (tier HIGH).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
