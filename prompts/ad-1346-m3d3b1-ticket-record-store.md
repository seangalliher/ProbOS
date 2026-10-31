# AD-1346 M3d3b1 (#1604): the work ticket's persisted record, four tables in `admission_shadow.db`

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-30
**Status:** build-ready. **Issue:** #1604 (AD-1346 M3, epic #1601). M3d3b is split into M3d3b1 (this contract: the tables, their writes and bounds, the report queries and the executed older-build check) and M3d3b2 (register R52: the recorder's offers, the chain test and the cost with the recorder). No new AD or BF number: M3 takes AD-1346 (`scripts/ad_ceiling.py` on 2026-10-30: ceiling AD-1355 from GitHub issue titles, next AD-1356; none allocated here). **Tier:** HIGH (M1, M2), docs (M3). Nothing parked.
**Dependencies:** AD-1346 M3d3a (`prompts/ad-1346-m3d3a-ticket-sinks.md`, with its amendment A1) merged to `origin/main`. The build base is `origin/main` at that merge.
**Anchors:** every SEARCH text in §7 and §8 was read on the detached checkout `60440cb2` (tree `2158c8d8`): the M3d2 head `302e6bf9` (tree `75aecaf1`) plus the M3d3a contract and its four milestones applied by tool (the M3d3a oracle; scratch commits, never pushed). 27 pairs (M1 25, M3 2), 1 new file besides this contract (`tests/test_ad1346_admission_ticket_record.py`), 2 regenerated files in M3 (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`). Dry-applied by the orchestrator on 2026-10-30, on `60440cb2` and on `41324376` (the M3d3a candidate head, tree `ec57d499`): 0 failures.
**Contract file:** `prompts/ad-1346-m3d3b1-ticket-record-store.md`.

**Identifiers.**
- Register rows: M3c1's R10 to R18, M3c2's R19 to R23, M3c3's R24 to R28, M3d1's R29 to R36, M3d2's R37 to R45, M3d3a's R46 to R51 and this contract's R52 to R57 are written "register R<n>".
- Tests: store tests S<n> (`tests/test_ad1346_admission_shadow_store.py`), parity tests P<n> (`tests/test_ad1346_admission_shadow_parity.py`), report tests Q<n> (`tests/test_ad1346_admission_shadow_report.py`), service tests T<n> (`tests/test_ad1346_admission_service.py`), M3d3a's SK1 to SK10, and this slice's TR1 to TR9 (`tests/test_ad1346_admission_ticket_record.py`).
- Mutation rows here are TRX-<n>.
- Decisions D137 to D148 are numbered after M3d3a's D123 to D136. #1604's properties are numbered 1 to 13.

**Which text describes the head.**
- **Records of the read tree `2158c8d8` (commit `60440cb2`):** the Status and Anchors paragraphs, §1, §11 (Verified Against Codebase, Absence Verified), the internal citations in §13, and every SEARCH text in §7 and §8. Each SEARCH text occurs once in its file on that tree, and no earlier pair of this contract edits those lines.
- **M3d3a is built and not merged** (2026-10-30): its candidate head after its A2 repair, `1ae78c8a` (tree `a7fd7db1`), is in cross-family review round 2. The orchestrator found the `src/` and `tests/` blobs of the earlier head `41324376` (tree `ec57d499`) equal to those of `60440cb2`, and `git diff --stat 41324376 1ae78c8a` lists only M3d3a's contract, `tests/test_ad1346_admission_ticket_sinks.py` and the two regenerated ledger files, so the records above describe the candidate's code except that test file. A review repair may change them. On the merged base, before the build, re-verify:
  - the files this contract **edits** that M3d3a also edits:
    - `tests/test_ad1346_admission_service.py` (M1-24 edits T14's `store.py` allowlist entry; M1-25 edits the T14 docstring lines M3d3a wrote);
    - `PROGRESS.md` (M3-01 anchors on M3d3a's paragraph head, whose date follows M3d3a's own date rule);
    - `DECISIONS.md` (M3-02 anchors on the heading that follows M3d3a's entry).
  - the M3d3a code it **cites**, unedited:
    - `AdmissionService._check_ticket` and `AdmissionService.hold` (D140's offer points, for M3d3b2);
    - `off_loop_checks` (the meaning of `off_loop`, D139);
    - `tests/test_ad1346_admission_ticket_sinks.py` (the fixture pattern TR2 follows; not imported).

  `git diff --stat 302e6bf9 60440cb2` lists none of `store.py`, `report.py`, `storage_declarations.py` or the store, parity and report tests, so their SEARCH texts do not depend on M3d3a's review. If the merged text of any file above differs, re-verify the pair or the citation against it.
- **Parts that describe the candidate's head and name no commit:** the Milestones and Tests lists, §2 to §6, §8's tracker text, §9, §10, §12, §14 and §15. Each count in them is measured by a named command, a focused gate or the broad gate, or is marked as a prediction.
- **Text inside the new-file block** (docstrings, comments) is head text and is reviewed as such.
- Where a record and the candidate differ, re-measure; the record does not bind.

**Milestones:**
- **M1 (HIGH):** the store, its declaration and the report, with the tests that pin them.
  - `probos.admission.store` gains four additive tables, `TicketSample`, `TicketBatch`, the field `ShadowBatch.tickets`, `ticket_digest`, `persisted_finding` and their constants. `write_batch` writes a batch's work-ticket part in its transaction, and `prune` bounds the work-ticket counts and markers.
  - The store declaration's title and notes name the four tables.
  - `REPORT_QUERIES` appends five `ticket_` queries.
  - S1, P6, Q1 and T14 are updated.
- **M2 (HIGH):** new `tests/test_ad1346_admission_ticket_record.py`, TR1 to TR9.
- **M3 (docs):** `PROGRESS.md`, `DECISIONS.md`, and the AD ledger regenerated by its tool.

**Process:**
- Each milestone is one Builder delegation and one local commit. Stage by explicit path, never `git add -A`. `git add` the new file before M2's focused gate.
- Commit subjects take the form `AD-1346 M3d3b1, M<n>: ... (#1604)`.
- D143's older-build check (§12) was run by the orchestrator before the build (2026-10-30, scratch trees of `41324376`) and printed every expected line. It is the check of record if `git diff --stat 41324376 <build base> -- src/probos/admission` and `git diff --stat <oracle M1 stage> <M1 commit> -- src/probos/admission` both print nothing; otherwise it is run again on the M1 stage, before the review.
- One cross-family review (`gpt-6.1-sol`) of M1 and M2 against §14.
- One mutation campaign of record on the M2 tree (§10). The orchestrator's pre-build census (2026-10-30, the oracle over `41324376`, `--expand-claims`) killed 18 of 18 rows by their Killed-by functions after an unmutated baseline of 9 passed. It is the campaign of record if `git diff --stat <oracle M2 stage> <M2 commit> -- src/probos/admission src/probos/agent_stop.py tests/fixtures/ad1346_shadow.py tests/test_ad1346_admission_ticket_record.py` prints nothing; otherwise the rows on a file that differs are rerun, and every row if any other listed file differs.
- The broad gate runs once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1346-m3d3b1 --receipt logs/gates/ad1346-m3d3b1.receipt.json`.

**Tests:**
- New: `tests/test_ad1346_admission_ticket_record.py` (M2), TR1 to TR9. The block in §7.10.N defines 9 `def test_` functions and no parametrised case (9 collected in the orchestrator's pre-build run, 2026-10-30; M2's gate records the count).
- Updated (M1), each file's `def test_` count unchanged:
  - `tests/test_ad1346_admission_shadow_store.py`: S1 (renamed; its table list) and its module bullet.
  - `tests/test_ad1346_admission_shadow_parity.py`: P6 (renamed; its table list) and its module bullet.
  - `tests/test_ad1346_admission_shadow_report.py`: Q1's names.
  - `tests/test_ad1346_admission_service.py`: T14's `store.py` allowlist and its docstring.
- The acceptance greps for the new test file are in §15.

## 1. Problem

- M3d3a's register R46 asks M3d3b for the persisted sink record, and none exists on this tree:
  - `admission_shadow.db` holds `schema_version` and five tables (`store.py:79-134`), none keyed by a ticket finding.
  - The work-ticket findings are counted only in `TicketRegistry.tally()` (`tickets.py:320-322`) and the sink checks handed over only in `AdmissionService.off_loop_checks()` (`service.py:254-256`). A restart loses both, and #1604 property 8 asks for a service-written durable record whose markers the report counts on the live vessel.
  - Absence: no Python file names `ticket_findings`, `TicketBatch` or `offer_ticket`.
- The findings to be kept are `TicketFinding` values (`tickets.py:143-164`).
  - `to_dict()` gives `TICKET_FINDING_KEYS` in order (`:65-68`).
  - `__post_init__` checks the operation (`TICKET_OPERATIONS`, `:63`) and the code (`TICKET_REASON_CODES`, `taxonomy.py:85-88`) only, not the work kind.
  - The registry fills `ticket_id` and `parent_id` with ids it issued as `secrets.token_hex(16)` (`:335`), or, for `ticket_unknown`, with a presented `WorkTicket`'s id cut to `SHOWN_CHARS` (`:76`, `:371-373`).
  - Its causes name the checked ticket's id or its parent's (`:236-248`, `:280-286`, `:342`, `:379-390`, `:435-439`).
  - A Captain's stop id is `uuid.uuid4().hex` (`agent_stop.py:424`), so it has the same 32-hex form as a ticket id.
- The writer M3d3b2 will use exists:
  - `ShadowRecorder._flush` builds a `ShadowBatch` from seven fields (`recorder.py:234-237`) and calls `write_batch` (`:241`), the one caller of `write_batch` in `src`;
  - `write_batch` writes in one transaction and rolls back on any `BaseException` (`store.py:349-365`);
  - `prune` runs in one transaction (`:368-403`).
- Hidden pins this slice meets:
  - S1 pins the file's table list (`tests/test_ad1346_admission_shadow_store.py:105-117`).
  - P6 pins the tables after a version-1 file opens (`tests/test_ad1346_admission_shadow_parity.py:286-305`).
  - Q1 pins `REPORT_QUERIES`'s names in order (`tests/test_ad1346_admission_shadow_report.py:32-35`), and Q5 that the report module's string constants begin with no write or schema keyword (`:108-114`).
  - T14 pins each persistence file's imports (`tests/test_ad1346_admission_service.py:99-113`; `store.py` at `:109-112`).
  - S11 pins the declaration's fields other than its text and its lifecycle owner (`tests/test_ad1346_admission_shadow_store.py:288-297`).

## 2. Solution

- **Tables.** `start` creates four more tables with `CREATE TABLE IF NOT EXISTS`, under `SCHEMA_VERSION` 1:
  - `ticket_findings` (counts per UTC day, operation, code, work kind and `off_loop`);
  - `ticket_samples` and `ticket_missing_samples` (two rings);
  - `ticket_markers` (per boot and UTC hour).
- **Writes.** `ShadowBatch` gains `tickets: TicketBatch`, empty by default. `write_batch` writes that part after the verdict tables' statements and before the one commit. A ring row holds `persisted_finding(finding)` as compact JSON: `to_dict()` with the ticket and parent ids shown as `ticket_digest`, the first 16 hex characters of their SHA-256.
- **Bounds.**
  - `prune` deletes finding days before the last `AGGREGATE_RETENTION_DAYS`, and marker hours as it deletes the verdict markers.
  - Each ring is trimmed when written.
  - The counts `prune` returns are unchanged.
- **Report.** Five `ticket_` queries are appended to `REPORT_QUERIES`.
- **Nothing in `src` fills it yet.** The recorder builds each batch without a work-ticket part, so on a vessel the four tables stay empty until M3d3b2 (register R52); the new test file writes them directly.

## 3. Decisions (numbered after M3d3a's D123 to D136)

- **D137 The split** (refines M3d3a's R46).
  - M3d3b1 (this contract) holds the four tables, their writes and bounds, the report queries, the declaration and the executed older-build check.
  - M3d3b2 (register R52) holds the recorder's `offer_ticket`, the offers in `_check_ticket` and `hold`, the chain test from a sink to a report query, a boot test that persists a sink's finding, and D146's cost measurement.
  - Reason: one slice would be about forty pairs and two test files (this contract's estimate). The persisted schema is the part that cannot be undone once a vessel writes it, so it gets a review of its own. M3b shipped a store before its seam callers.
  - Rejected:
    - one slice;
    - the store with the recorder first (about 37 pairs, with the writer still reviewed with no producer);
    - the offers first (no table to write to).
- **D138 What is kept for each outcome.** (M3d3b2 makes the offers; this slice defines the shapes and writes them.)
  - Every finding offered is counted under its key, `ticket_issued` and `ticket_live` included.
  - A finding is sampled unless its code is `ticket_issued` or `ticket_live`.
  - `ticket_missing` samples have a ring of their own (`ticket_missing_samples`, 1,000). Model and tool calls that reach a sink outside a held unit count `ticket_missing` (registers R37, R38), so one shared ring of the newest 5,000 could hold only `ticket_missing` rows and push out the rarer `ticket_revoked`, `ticket_principal_mismatch`, `ticket_unknown` and issue-refusal samples, which are #1604 property 3's and property 5's evidence.
  - The fields kept are `TicketFinding.to_dict()` (the ids as in D144), plus boot, hour, wall time and `off_loop` as columns.
    - `principal_key` and `presented_key` are slot keys or presented ids cut to 64 characters, and `stop_id` is the Captain's order's id. M3b's verdict samples already persist `key`, `presented_id` and `stop_id`.
    - No presented object is persisted: a `ticket_unknown` finding carries only the presented id's string, and it is digested.
  - Rejected:
    - one ring for all sampled codes (R46's direction), for the flooding above;
    - counts only (no finding could be classified);
    - sampling `ticket_issued` and `ticket_live` (they flood every ring).
- **D139 Tables, keys and bounds.**
  - `ticket_findings`: PK (day, operation, code, work kind, `off_loop`).
    - `off_loop` is 1 for a sink check handed to the service's loop from another thread or loop (M3d3a's D128; register R49).
    - Per-day bound for findings whose work kind is in `WORK_KINDS` or empty: `len(TICKET_OPERATIONS)` 3 × `len(TICKET_REASON_CODES)` 12 × (`len(WORK_KINDS)` 12 + 1) × 2 = 936 rows, and 32,760 over 35 days, below `AGGREGATE_ROW_LIMIT` (100,000). TR6 pins the inequality.
    - The store does not check a work kind; `TicketFinding` does not either. M3d3b2's `offer_ticket` checks it (register R53).
    - Pruned by day like `shadow_parity`, with no row-limit loop of its own. A wall clock that steps back can leave more days (M3b's R2, the parity precedent).
    - Depth stays out of the key: ×4 would give 131,040 rows over 35 days.
  - Rings: `ticket_samples` (`TICKET_SAMPLE_RING_SIZE` 5,000) and `ticket_missing_samples` (`TICKET_MISSING_RING_SIZE` 1,000), each trimmed after its own insert by `seq` as `shadow_samples` is.
    - SQLite's AUTOINCREMENT ids are monotonic and may have gaps (§11), so a ring keeps at most its size of its newest rows.
    - The rings are not pruned by day (register R56).
  - `ticket_markers`: PK (boot, hour); pruned like `shadow_markers` (`MARKER_RETENTION_DAYS`, then `MARKER_ROW_LIMIT`, oldest first).
  - **The new prune statements' edges.** They run after the existing ones, in the same transaction, and each computes its cutoff with an expression that an existing statement before it computes from the same `now`. A cutoff that raises therefore raises at an existing statement before them, and they add no raising cutoff of their own.
  - **A restart.** The registry's tally and `off_loop_checks` are per service and are not restored. The persisted counts add up, per day, what each boot's committed writes held, and the markers are per boot.
  - Rejected:
    - a work-ticket column on `shadow_aggregates` (changes its key);
    - depth or principal in the key (bound above the limit, or no bound).
- **D140 The writer and its thread** (binding on M3d3b2; this slice builds no writer).
  - The existing `ShadowRecorder`, in the same `write_batch` transaction as the verdicts, through `offer_ticket(finding, *, off_loop)`:
    - it adds to an in-memory `TicketBatch`, awaits nothing and does no I/O;
    - it validates `type(finding) is TicketFinding`, an exact `bool` and a work kind in `WORK_KINDS` or `""`, before counting;
    - it bounds new pending keys by `PENDING_KEY_LIMIT`, and samples by buffers equal to the ring sizes.
  - **Offer points:**
    - `_check_ticket`, after its `off_loop` count, inside its `except Exception`. It runs on the service's loop when the service has one (D128), so the offer runs there too.
    - `hold`, inside its `except Exception`, after the issue and before `CURRENT_TICKET.set`. It runs on its caller's thread, as `shadow`'s offer does.
  - **Fail-open:**
    - no recorder offers nothing;
    - a recorder whose `stop` began counts `ticket_late`;
    - a full buffer counts `ticket_dropped` or `ticket_samples_dropped`;
    - an `Exception` from the offer is counted once in the service's `failures` by the existing `except` (the registry has already counted the finding in its tally).
  - In `hold`, a raising offer returns `NO_HOLD` with the carrier untouched, and the issued entry stays registered until it expires (injected only). An offer after the `set` would add a path to register R45.
  - Rejected:
    - a second writer, a flusher of its own on the same file (two writers contend for the file's write lock under `busy_timeout`, with a second lifecycle step and boot id);
    - the registry writing (it would couple the authority to I/O, and `tickets.py` is held to the decision files' rules by T14);
    - an offer after the carrier's `set`.
- **D141 The markers.**
  - A new table, `ticket_markers` (offered, written, dropped, samples dropped, per boot and UTC hour). `written` is what a committed write added to `ticket_findings` for the hour, so the producer marker (offered) and the consumer marker (written) reach the file in the transaction of the counts they describe, as D10's verdict markers do.
  - `ticket_late` stays in memory, like `late`.
  - Rejected:
    - columns on `shadow_markers` (`ALTER TABLE`, a migration);
    - the verdict markers counting findings too (property 8 counts each producer).
- **D142 The report queries**, appended to `REPORT_QUERIES`; none of the existing names changes:
  - `ticket_findings_by_operation` (since day);
  - `ticket_samples` and `ticket_missing_samples` (limit, newest first);
  - `ticket_markers_by_boot`;
  - `ticket_days_recorded`.

  Rejected: one query that takes a table name (`run_query` accepts frozen names only).
- **D143 Compatibility.**
  - `SCHEMA_VERSION` stays 1, and the four tables are additive. `start` creates them on any version-1 file, and a file an older build wrote keeps its rows (TR7).
  - A build without them (the build base, whose store is M3c's): its `start` checks only the version row and creates only its own tables; its `prune` and report queries name only its own tables. So it opens, writes, prunes and queries a file this build wrote, and none of its `start`, write, `prune` or report statements names the four. While such a build runs, the work-ticket rows are not pruned (register R54).
  - The `ticket_` queries raise `sqlite3.OperationalError` on a file without the tables (TR7; register R55).
  - **Executed** by the orchestrator before the build (2026-10-30, §12): each command exited 0 and printed its expected lines. Process says when it is run again. Its output is recorded in a DECISIONS bullet, as M3c1's D58 check was.
  - Rejected:
    - version 2 (an older build would refuse the file and a revert would lose the evidence: a persisted-schema decision for the Captain);
    - a separate file (a second declaration, lifecycle step and transaction).
- **D144 Ticket ids as digests.**
  - `ticket_digest(value)` is the first `TICKET_DIGEST_CHARS` (16) hex characters of SHA-256 over UTF-8, or `""` for `""`.
  - `persisted_finding` replaces `ticket_id` and `parent_id` by their digest. Where one of them is 32 lowercase hex characters (the form `secrets.token_hex(16)` gives), it also replaces each occurrence of it in `cause`.
  - It keys on the finding's own ids, not on any 32-hex run, because a stop id has that form too (`agent_stop.py:424`) and must stay readable; the field `stop_id` is kept.
  - Reason: a ticket id is a bearer reference in its registry, and OWASP ASVS 4, requirement 7.1.1, asks that session tokens be logged in hashed form. Today only code in the vessel's own process could present one (#1604 blind spot 5). This keeps the record safe if M4 or AD-1342 lets a ticket cross a process boundary, and keeps correlation within the file.
  - Rejected:
    - raw ids (correct today, but bearer references in a backed-up file);
    - dropping the ids and the cause (loses parent links and property 9's cause);
    - digesting every 32-hex run in the cause (would hide stop ids).
- **D145 Census and structure pins.**
  - The store declaration keeps its id, owner, criticality, retention, backup and restore; its title, retention note and notes name the four tables.
  - `check_store_registry.py --check` passed in the orchestrator's pre-build run (2026-10-30) with `docs/development/store-baseline.yaml` unchanged and the base's numbers, as with M3c1's two tables.
  - `AdmissionShadowStore` gains no method: the helpers are module functions. Its span grows from 173 to 218 lines by `ast` in the same run, against the trigger `span > 500`. `docs/development/architecture-baseline.yaml` has no row for it.
  - T14's `store.py` allowlist gains `hashlib`, `re` and `probos.admission.tickets` (a `TYPE_CHECKING` import).
- **D146 The cost with the recorder** (#1604 property 7; run by M3d3b2 on its M1 stage, on the Captain's Windows host, CPython 3.12.13, idle).
  - Setup: D132's, plus `recorder=ShadowRecorder(store)` over an `AdmissionShadowStore` started in a temporary directory.
    - The recorder is not started, so no flush runs during a round.
    - A fresh registry and recorder per round.
  - Timing and variants (a) to (d): D132's. Report each median and 99th percentile beside D132's figures without a recorder.
  - In (d) each check counts `ticket_missing`: the first 1,000 offers of a round keep a sample and later ones count a dropped sample. Report which path dominates.
  - Also report the time of one `write_batch` of one round's work-ticket part, 20 times. This is the flusher's cost, off the hot path.
  - Prediction: none in figures. The offer adds one wall-clock read, one hour lookup, two or three dict updates and, for a sampled code, one list append.
- **D147 The clock-reset rule** (refines D106, D121 and D134, which said a recorder or report fix does not restart; they were written when the recorder held no sink record).
  - This slice changes no check and makes no offer, so nothing restarts. All of M3d precedes the M3e deploy that starts the shadow period.
  - From M3d3b2's deploy, during the period, a fix that changes which work-ticket findings are kept or under which key restarts the 7 days for the sink records. That covers `offer_ticket`'s key and validation, the two offers, the work-ticket rows and statements in `write_batch`, and the work-ticket prune.
  - A fix to a report query, the declaration's text, the markers' arithmetic or `ticket_digest` restarts nothing. Property 8's marker counts are then taken from boots after that fix.
- **D148 Left out.**
  - The offers, the chain test, the boot test and the cost: M3d3b2 (R52).
  - Counting `TicketHold.end`'s passed-over failures (register R41): M3e.
  - Registers R44 and R45's repairs: the follow-up they name.
  - The system-principal census and the remaining effect points: M3e.

## 4. Milestones and focused gates

| Milestone | Files | Focused gate |
|---|---|---|
| M1 | `src/probos/admission/store.py`, `src/probos/admission/storage_declarations.py`, `src/probos/admission/report.py`, `tests/test_ad1346_admission_shadow_store.py`, `tests/test_ad1346_admission_shadow_parity.py`, `tests/test_ad1346_admission_shadow_report.py`, `tests/test_ad1346_admission_service.py` | `pytest tests/test_ad1346_admission_shadow_store.py tests/test_ad1346_admission_shadow_recorder.py tests/test_ad1346_admission_shadow_report.py tests/test_ad1346_admission_shadow_parity.py tests/test_ad1346_admission_shadow_boot.py tests/test_ad1346_admission_shadow_switch.py tests/test_ad1346_admission_service.py tests/test_ad1256_store_registry.py tests/test_issue1419_failed_start_rollback.py -n 0`; `python -P scripts/check_architecture_principles.py --check`; `python -P scripts/check_store_registry.py --check` |
| M2 | new `tests/test_ad1346_admission_ticket_record.py` | `git add` the new file, then `pytest tests/test_ad1346_admission_ticket_record.py tests/test_ad1346_admission_shadow_store.py tests/test_ad1346_admission_shadow_report.py -n 0`; `pytest tests/test_ad1346_admission_ticket_record.py --collect-only -q -p no:cacheprovider -n 0` (record the count) |
| M3 | `PROGRESS.md`, `DECISIONS.md`; regenerated `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | `python -P scripts/gen_ad_ledger.py`, then `python -P scripts/gen_ad_ledger.py --check`, then `pytest tests/test_ad1184_ad_ledger.py -n 0` |

## 5. Consumers of every value this changes

- **`ShadowBatch.tickets`** (default: an empty `TicketBatch`).
  - Read by `write_batch`.
  - `ShadowRecorder._flush` builds batches without it, and `_restore` reads the other seven fields.
  - Every test that builds a `ShadowBatch` passes the first five fields, by position or (Q2) by keyword, with or without `parity` and `disagreements`; none passes `tickets` except the new file's `_with_tickets`.
- **`TicketSample`, `TicketBatch`, `ticket_digest`, `persisted_finding`, `TICKET_SAMPLE_RING_SIZE`, `TICKET_MISSING_RING_SIZE`, `TICKET_DIGEST_CHARS`.** Used by `store.py` and the new test file; D143's check (§12) also builds a `TicketBatch` of `TicketSample`s. Elsewhere in `src` only the declaration's notes name two of them (the ring sizes), as text; before the slice no `.py` file named any of them (Grep on `82505f45`, 2026-10-30).
- **The four tables.**
  - Created by `start` (`_SCHEMA`) on any version-1 file.
  - Written by `write_batch`.
  - Deleted from by `write_batch`'s ring trims and by `prune`.
  - Read by the five new report queries, D143's check and the new test file; TR7 also drops them from a file.
  - `check_store_registry.py` finds their `CREATE TABLE` statements in `store.py`, the declaration's owner module (§12), and the declaration's `backup="included"` covers the file that holds them.
- **`REPORT_QUERIES`** (five names appended). `run_query` admits them by name. Q1 pins the names in order and requires each to begin with `SELECT ` and hold no `;`; Q5 reads every string constant in `report.py`. In the new file TR7 selects the names that begin with `ticket_`, and TR7 and TR8 run each; D143's check runs every name of the build it imports. The existing names, their SQL, P12 and Q2 are unchanged.
- **The declaration's text.** Read by people. `check_store_registry.py` requires the title not to be blank.
- **T14's `store.py` allowlist.** Read by T14.

## 6. Tests

| File | M | Cases | What |
|---|---|---|---|
| `tests/test_ad1346_admission_ticket_record.py` | M2 | 9 (the block's `def test_` count; record the collected number at M2's gate) | TR1 to TR9: real `AdmissionShadowStore` under `tmp_path`, a real `TicketRegistry` over a real `AgentStopService` for TR2, the report over `mode=ro` connections |
| `tests/test_ad1346_admission_shadow_store.py` | M1 | unchanged count | S1 renamed; its table list and module bullet |
| `tests/test_ad1346_admission_shadow_parity.py` | M1 | unchanged count | P6 renamed; its table list and module bullet |
| `tests/test_ad1346_admission_shadow_report.py` | M1 | unchanged count | Q1's names |
| `tests/test_ad1346_admission_service.py` | M1 | unchanged count | T14's `store.py` allowlist and docstring |

## 7. The contract

### 7.1 M1: `src/probos/admission/store.py`

**M1-01**

SEARCH:
```
The store #1601's evidence 2, 4, 7 and 8 read (memo D9: a dedicated store, not AD-1195 durable
events). It holds one ``schema_version`` row and five tables, each bounded by a module constant
(memo D10); AD-1346 M3c added the last two:
```
REPLACE:
```
The store #1601's evidence 2, 4, 7 and 8 read (memo D9: a dedicated store, not AD-1195 durable
events). It holds one ``schema_version`` row and nine tables, each pruned or trimmed under a module constant
(memo D10); AD-1346 M3c added ``shadow_parity`` and ``shadow_disagreements``, and AD-1346 M3d3b the
four ``ticket_`` tables:
```

**M1-02**

SEARCH:
```
- ``shadow_disagreements`` (M3c): verdicts whose outcome differs from the site's own, as
  ``AdmissionVerdict.to_dict()`` JSON with today's outcome beside it. Each ``write_batch`` that adds
  one then keeps the newest ``DISAGREEMENT_RING_SIZE`` rows.

The store is opened through the ``ConnectionFactory``. ``start`` opens a file whose
``schema_version`` holds exactly one row of ``SCHEMA_VERSION``, writes that row to a file with no
row, and refuses a file with any other rows without writing to it; this module has no migration.
M3c's two tables are additive and keep version 1 (D58): ``start`` creates them on any version-1
file, so a file the M3b build wrote opens here with its rows unchanged, and the M3b build's
``start`` accepts a file this build wrote, because it checks only the version row and creates only
its own three tables.
"""
```
REPLACE:
```
- ``shadow_disagreements`` (M3c): verdicts whose outcome differs from the site's own, as
  ``AdmissionVerdict.to_dict()`` JSON with today's outcome beside it. Each ``write_batch`` that adds
  one then keeps the newest ``DISAGREEMENT_RING_SIZE`` rows.
- ``ticket_findings`` (M3d3b): work-ticket finding counts per (UTC day, operation, code, work kind,
  ``off_loop``), the flag written as an integer. ``prune`` deletes the days before the last
  ``AGGREGATE_RETENTION_DAYS``. It has no row limit of its own: for keys whose operation and code a
  ``TicketFinding`` accepts, whose work kind is in ``WORK_KINDS`` or empty and whose ``off_loop`` is a
  bool, one day holds at most
  len(TICKET_OPERATIONS) * len(TICKET_REASON_CODES) * (len(WORK_KINDS) + 1) * 2 rows, a test pins
  that 35 such days stay below ``AGGREGATE_ROW_LIMIT``, and a wall clock that steps back can leave
  more days than 35. This module checks no part of a key.
- ``ticket_samples`` and ``ticket_missing_samples`` (M3d3b): findings as ``persisted_finding`` JSON
  (``TicketFinding.to_dict()`` with the ticket and parent ids shown as ``ticket_digest``), a batch's
  ``missing`` samples in the second table and its other samples in the first. Each ``write_batch``
  that adds rows to one of them then deletes that table's rows whose ``seq`` is at least
  ``TICKET_SAMPLE_RING_SIZE`` (``TICKET_MISSING_RING_SIZE``) below its largest, so at most that many
  remain, the newest.
- ``ticket_markers`` (M3d3b): per (boot, UTC hour), a batch's offered, dropped and samples-dropped
  counts for its work-ticket part and the findings the write added to ``ticket_findings``. ``prune``
  deletes them as it deletes ``shadow_markers``.

The store is opened through the ``ConnectionFactory``. ``start`` opens a file whose
``schema_version`` holds exactly one row of ``SCHEMA_VERSION``, writes that row to a file with no
row, and refuses a file with any other rows without writing to it; this module has no migration.
M3c's two tables are additive and keep version 1 (D58): ``start`` creates them on any version-1
file, so a file the M3b build wrote opens here with its rows unchanged, and the M3b build's
``start`` accepts a file this build wrote, because it checks only the version row and creates only
its own three tables. AD-1346 M3d3b's four tables are additive in the same way (D143): ``start``
creates them on any version-1 file, and the ``start``, ``prune`` and report queries of a build
without them neither read nor write them.
"""
```

**M1-03**

SEARCH:
```
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Final

from probos.storage.sqlite_factory import default_factory

if TYPE_CHECKING:
    from probos.admission.record import AdmissionVerdict
    from probos.protocols import ConnectionFactory, DatabaseConnection
```
REPLACE:
```
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Final

from probos.storage.sqlite_factory import default_factory

if TYPE_CHECKING:
    from probos.admission.record import AdmissionVerdict
    from probos.admission.tickets import TicketFinding
    from probos.protocols import ConnectionFactory, DatabaseConnection
```

**M1-04**

SEARCH:
```
#: AD-1346 M3c (D58): the disagreement samples kept, the newest.
DISAGREEMENT_RING_SIZE: Final = 1_000
```
REPLACE:
```
#: AD-1346 M3c (D58): the disagreement samples kept, the newest.
DISAGREEMENT_RING_SIZE: Final = 1_000
#: AD-1346 M3d3b (D139): a ``write_batch`` adding ``ticket_samples`` rows keeps at most this many, the newest.
TICKET_SAMPLE_RING_SIZE: Final = 5_000
#: AD-1346 M3d3b (D138, D139): a ``write_batch`` adding ``ticket_missing_samples`` rows keeps at most this many, the newest.
TICKET_MISSING_RING_SIZE: Final = 1_000
#: AD-1346 M3d3b (D144): the hex characters of ``ticket_digest``.
TICKET_DIGEST_CHARS: Final = 16
```

**M1-05**

SEARCH:
```
    latency_ns    INTEGER NOT NULL,
    verdict_json  TEXT NOT NULL
);
"""
```
REPLACE:
```
    latency_ns    INTEGER NOT NULL,
    verdict_json  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_findings (
    day       TEXT NOT NULL,
    operation TEXT NOT NULL,
    code      TEXT NOT NULL,
    work_kind TEXT NOT NULL,
    off_loop  INTEGER NOT NULL,
    findings  INTEGER NOT NULL,
    PRIMARY KEY (day, operation, code, work_kind, off_loop)
);
CREATE TABLE IF NOT EXISTS ticket_samples (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id      TEXT NOT NULL,
    hour         TEXT NOT NULL,
    recorded_at  REAL NOT NULL,
    operation    TEXT NOT NULL,
    code         TEXT NOT NULL,
    work_kind    TEXT NOT NULL,
    off_loop     INTEGER NOT NULL,
    finding_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_missing_samples (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id      TEXT NOT NULL,
    hour         TEXT NOT NULL,
    recorded_at  REAL NOT NULL,
    operation    TEXT NOT NULL,
    code         TEXT NOT NULL,
    work_kind    TEXT NOT NULL,
    off_loop     INTEGER NOT NULL,
    finding_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_markers (
    boot_id         TEXT NOT NULL,
    hour            TEXT NOT NULL,
    offered         INTEGER NOT NULL,
    written         INTEGER NOT NULL,
    dropped         INTEGER NOT NULL,
    samples_dropped INTEGER NOT NULL,
    PRIMARY KEY (boot_id, hour)
);
"""
```

**M1-06**

SEARCH:
```
_DELETE_OLDEST_MARKERS: Final = (
    "DELETE FROM shadow_markers WHERE rowid IN (SELECT rowid FROM shadow_markers ORDER BY hour, boot_id LIMIT ?)"
)
```
REPLACE:
```
_DELETE_OLDEST_MARKERS: Final = (
    "DELETE FROM shadow_markers WHERE rowid IN (SELECT rowid FROM shadow_markers ORDER BY hour, boot_id LIMIT ?)"
)
#: AD-1346 M3d3b (D139): the work-ticket tables' statements, in the shape of the verdict tables' above.
_UPSERT_TICKET_FINDING: Final = (
    "INSERT INTO ticket_findings (day, operation, code, work_kind, off_loop, findings) VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (day, operation, code, work_kind, off_loop) DO UPDATE SET findings = findings + excluded.findings"
)
_INSERT_TICKET_SAMPLE: Final = (
    "INSERT INTO ticket_samples (boot_id, hour, recorded_at, operation, code, work_kind, off_loop, finding_json) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
_TRIM_TICKET_SAMPLES: Final = "DELETE FROM ticket_samples WHERE seq <= (SELECT MAX(seq) FROM ticket_samples) - ?"
_INSERT_TICKET_MISSING: Final = (
    "INSERT INTO ticket_missing_samples (boot_id, hour, recorded_at, operation, code, work_kind, off_loop, "
    "finding_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
_TRIM_TICKET_MISSING: Final = (
    "DELETE FROM ticket_missing_samples WHERE seq <= (SELECT MAX(seq) FROM ticket_missing_samples) - ?"
)
_UPSERT_TICKET_MARKER: Final = (
    "INSERT INTO ticket_markers (boot_id, hour, offered, written, dropped, samples_dropped) "
    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (boot_id, hour) DO UPDATE SET "
    "offered = offered + excluded.offered, written = written + excluded.written, "
    "dropped = dropped + excluded.dropped, samples_dropped = samples_dropped + excluded.samples_dropped"
)
_PRUNE_TICKET_FINDINGS: Final = "DELETE FROM ticket_findings WHERE day < ?"
_PRUNE_TICKET_MARKERS: Final = "DELETE FROM ticket_markers WHERE hour < ?"
_COUNT_TICKET_MARKERS: Final = "SELECT COUNT(*) FROM ticket_markers"
_DELETE_OLDEST_TICKET_MARKERS: Final = (
    "DELETE FROM ticket_markers WHERE rowid IN (SELECT rowid FROM ticket_markers ORDER BY hour, boot_id LIMIT ?)"
)
#: AD-1346 M3d3b (D144): the form of an id the ticket registry issues (``secrets.token_hex(16)``).
_ISSUED_ID: Final = re.compile(r"[0-9a-f]{32}")
```

**M1-07**

SEARCH:
```
    latency_ns: int
    today_outcome: str


@dataclass(frozen=True, slots=True)
class ShadowBatch:
    """What one ``write_batch`` writes. Aggregate keys are (hour, work kind, seam, outcome, reason code, bucket).

    AD-1346 M3c: parity keys are (hour, work kind, seam, today's outcome, outcome, reason code). Both
    fields it added default to empty, so a batch built from the first five fields writes what M3b wrote.
    """

    aggregates: dict[tuple[str, str, str, str, str, int], int]
    samples: list[ShadowSample]
    offered: dict[str, int]
    dropped: dict[str, int]
    samples_dropped: dict[str, int]
    parity: dict[tuple[str, str, str, str, str, str], int] = field(default_factory=dict)
    disagreements: list[ShadowDisagreement] = field(default_factory=list)
```
REPLACE:
```
    latency_ns: int
    today_outcome: str


@dataclass(frozen=True, slots=True)
class TicketSample:
    """AD-1346 M3d3b (D138): one work-ticket finding for a ring, with the UTC hour, the wall time and the ``off_loop``
    flag its row is written with."""

    hour: str
    recorded_at: float
    finding: TicketFinding
    off_loop: bool


@dataclass(frozen=True, slots=True)
class TicketBatch:
    """AD-1346 M3d3b (D139): the work-ticket part of one ``write_batch``; every field defaults to empty.

    Finding keys are (hour, operation, code, work kind, off_loop). ``samples`` is written to ``ticket_samples`` and
    ``missing`` to ``ticket_missing_samples``; the store does not read a sample's code to choose. ``offered``,
    ``dropped`` and ``samples_dropped`` are counts by hour for the marker rows.
    """

    findings: dict[tuple[str, str, str, str, bool], int] = field(default_factory=dict)
    samples: list[TicketSample] = field(default_factory=list)
    missing: list[TicketSample] = field(default_factory=list)
    offered: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    samples_dropped: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ShadowBatch:
    """What one ``write_batch`` writes. Aggregate keys are (hour, work kind, seam, outcome, reason code, bucket).

    AD-1346 M3c: parity keys are (hour, work kind, seam, today's outcome, outcome, reason code). Both
    fields it added default to empty, so a batch built from the first five fields writes what M3b wrote.
    AD-1346 M3d3b: ``tickets`` defaults to an empty ``TicketBatch``, so a batch built without it writes what M3c
    wrote.
    """

    aggregates: dict[tuple[str, str, str, str, str, int], int]
    samples: list[ShadowSample]
    offered: dict[str, int]
    dropped: dict[str, int]
    samples_dropped: dict[str, int]
    parity: dict[tuple[str, str, str, str, str, str], int] = field(default_factory=dict)
    disagreements: list[ShadowDisagreement] = field(default_factory=list)
    tickets: TicketBatch = field(default_factory=TicketBatch)
```

**M1-08**

SEARCH:
```
class AdmissionShadowStore:
    """Ship's Computer store: the shadow admission decision's durable record (AD-1346 M3b)."""
```
REPLACE:
```
def ticket_digest(value: str) -> str:
    """AD-1346 M3d3b (D144): a ticket id as a ring shows it: the first ``TICKET_DIGEST_CHARS`` hex characters of its
    SHA-256 over UTF-8, or ``""`` for ``""``."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:TICKET_DIGEST_CHARS] if value else ""


def persisted_finding(finding: TicketFinding) -> dict[str, object]:
    """AD-1346 M3d3b (D144): ``finding.to_dict()`` as a ring keeps it.

    ``ticket_id`` and ``parent_id`` are replaced by their ``ticket_digest``. Where one of them is 32 lowercase hex
    characters, the form of an id the ticket registry issues, each occurrence of it in ``cause`` is replaced by its
    digest too. Every other value is the finding's, the stop's id included.
    """
    cause = finding.cause
    for raw in (finding.ticket_id, finding.parent_id):
        if _ISSUED_ID.fullmatch(raw):
            cause = cause.replace(raw, ticket_digest(raw))
    body = finding.to_dict()
    body["ticket_id"] = ticket_digest(finding.ticket_id)
    body["parent_id"] = ticket_digest(finding.parent_id)
    body["cause"] = cause
    return body


def _ticket_sample_row(boot_id: str, sample: TicketSample) -> tuple[str, str, float, str, str, str, int, str]:
    """AD-1346 M3d3b: one ring row: the sample's columns, then its ``persisted_finding`` as compact JSON."""
    finding = sample.finding
    return (
        boot_id, sample.hour, sample.recorded_at, finding.operation, finding.code, finding.work_kind,
        int(sample.off_loop), json.dumps(persisted_finding(finding), separators=(",", ":")),
    )


class AdmissionShadowStore:
    """Ship's Computer store: the durable record of the shadow admission decision (AD-1346 M3b) and of the work
    ticket's findings (AD-1346 M3d3b)."""
```

**M1-09**

SEARCH:
```
        AD-1346 M3c: each parity key's count is added to its row for that UTC day, and each
        disagreement becomes a row, after which the newest ``DISAGREEMENT_RING_SIZE`` are kept. An
        exception from the statements or the commit rolls the transaction back and propagates.
        Raises ``RuntimeError`` when the store is not open.
```
REPLACE:
```
        AD-1346 M3c: each parity key's count is added to its row for that UTC day, and each
        disagreement becomes a row, after which the newest ``DISAGREEMENT_RING_SIZE`` are kept.
        AD-1346 M3d3b: from ``batch.tickets``, each finding key's count is added to its
        ``ticket_findings`` row for that UTC day; each of ``samples`` becomes a ``ticket_samples`` row and
        each of ``missing`` a ``ticket_missing_samples`` row, after which a table that gained rows keeps
        those whose ``seq`` is less than its ring size below its largest; the ``ticket_markers`` row of
        each hour in that part gains the hour's offered, dropped and samples-dropped counts and the
        findings this call added for it. The number returned leaves the findings out. An exception from
        the statements or the commit rolls the transaction back and propagates. Raises ``RuntimeError``
        when the store is not open.
```

**M1-10**

SEARCH:
```
            for hour in hours
        ]
        try:
            if aggregates:
```
REPLACE:
```
            for hour in hours
        ]
        tickets = batch.tickets  # AD-1346 M3d3b (D139): the work-ticket part, written in the same transaction
        ticket_written: dict[str, int] = {}
        ticket_findings: list[tuple[str, str, str, str, int, int]] = []
        for (hour, operation, code, work_kind, off_loop), count in tickets.findings.items():
            ticket_findings.append((hour[:10], operation, code, work_kind, int(off_loop), count))
            ticket_written[hour] = ticket_written.get(hour, 0) + count
        ticket_samples = [_ticket_sample_row(boot_id, sample) for sample in tickets.samples]
        ticket_missing = [_ticket_sample_row(boot_id, sample) for sample in tickets.missing]
        ticket_hours = sorted(
            set(tickets.offered) | set(ticket_written) | set(tickets.dropped) | set(tickets.samples_dropped)
        )
        ticket_markers = [
            (
                boot_id, hour, tickets.offered.get(hour, 0), ticket_written.get(hour, 0), tickets.dropped.get(hour, 0),
                tickets.samples_dropped.get(hour, 0),
            )
            for hour in ticket_hours
        ]
        try:
            if aggregates:
```

**M1-11**

SEARCH:
```
            if markers:
                await db.executemany(_UPSERT_MARKER, markers)
            await db.commit()
```
REPLACE:
```
            if markers:
                await db.executemany(_UPSERT_MARKER, markers)
            if ticket_findings:
                await db.executemany(_UPSERT_TICKET_FINDING, ticket_findings)
            if ticket_samples:
                await db.executemany(_INSERT_TICKET_SAMPLE, ticket_samples)
                await db.execute(_TRIM_TICKET_SAMPLES, (TICKET_SAMPLE_RING_SIZE,))
            if ticket_missing:
                await db.executemany(_INSERT_TICKET_MISSING, ticket_missing)
                await db.execute(_TRIM_TICKET_MISSING, (TICKET_MISSING_RING_SIZE,))
            if ticket_markers:
                await db.executemany(_UPSERT_TICKET_MARKER, ticket_markers)
            await db.commit()
```

**M1-12**

SEARCH:
```
        AD-1346 M3c: the same transaction deletes the parity rows of days before the last
        ``AGGREGATE_RETENTION_DAYS``; the counts returned leave them out. Raises ``RuntimeError`` when
        the store is not open; an exception from SQLite rolls the transaction back and propagates.
```
REPLACE:
```
        AD-1346 M3c: the same transaction deletes the parity rows of days before the last
        ``AGGREGATE_RETENTION_DAYS``; the counts returned leave them out. AD-1346 M3d3b: it also deletes
        the ``ticket_findings`` rows of those days, and the ``ticket_markers`` rows of days before the last
        ``MARKER_RETENTION_DAYS`` and then the oldest hours while more than ``MARKER_ROW_LIMIT`` remain; the
        counts returned leave these out too, and the two work-ticket rings are not pruned (each is trimmed
        when written). Raises ``RuntimeError`` when the store is not open; an exception from SQLite rolls the
        transaction back and propagates.
```

**M1-13**

SEARCH:
```
            if count > MARKER_ROW_LIMIT:
                cursor = await db.execute(_DELETE_OLDEST_MARKERS, (count - MARKER_ROW_LIMIT,))
                markers += cursor.rowcount
            await db.commit()
```
REPLACE:
```
            if count > MARKER_ROW_LIMIT:
                cursor = await db.execute(_DELETE_OLDEST_MARKERS, (count - MARKER_ROW_LIMIT,))
                markers += cursor.rowcount
            await db.execute(_PRUNE_TICKET_FINDINGS, (utc_day(now - (AGGREGATE_RETENTION_DAYS - 1) * DAY_SECONDS),))
            await db.execute(_PRUNE_TICKET_MARKERS, (utc_day(now - (MARKER_RETENTION_DAYS - 1) * DAY_SECONDS),))
            async with db.execute(_COUNT_TICKET_MARKERS) as cursor:
                (count,) = await cursor.fetchone()
            if count > MARKER_ROW_LIMIT:
                await db.execute(_DELETE_OLDEST_TICKET_MARKERS, (count - MARKER_ROW_LIMIT,))
            await db.commit()
```

### 7.2 M1: `src/probos/admission/storage_declarations.py`

**M1-14**

SEARCH:
```
        title="The shadow admission decision's counts, would-refuse samples, markers, parity counts and disagreement samples (AD-1346 M3b, M3c)",
```
REPLACE:
```
        title="The shadow admission decision's counts, would-refuse samples, markers, parity counts and disagreement samples, and the work ticket's finding counts, samples and markers (AD-1346 M3b, M3c, M3d3b)",
```

**M1-15**

SEARCH:
```
            "AD-1346 M3c: prune deletes the parity counts of days before the last AGGREGATE_RETENTION_DAYS UTC "
            "days, and each write_batch that adds disagreement samples keeps the newest DISAGREEMENT_RING_SIZE."
```
REPLACE:
```
            "AD-1346 M3c: prune deletes the parity counts of days before the last AGGREGATE_RETENTION_DAYS UTC "
            "days, and each write_batch that adds disagreement samples keeps the newest DISAGREEMENT_RING_SIZE. "
            "AD-1346 M3d3b: prune deletes the work-ticket finding counts of days before the last "
            "AGGREGATE_RETENTION_DAYS UTC days and the work-ticket markers as it deletes the markers; each "
            "write_batch that adds rows to a work-ticket ring keeps at most the newest TICKET_SAMPLE_RING_SIZE "
            "or TICKET_MISSING_RING_SIZE rows of that ring."
```

**M1-16**

SEARCH:
```
            "registry. Opened through the ConnectionFactory. Tables: schema_version, shadow_aggregates, "
            "shadow_samples, shadow_markers and, from AD-1346 M3c, shadow_parity and shadow_disagreements. "
            "start opens a file whose schema_version holds exactly "
            "one row of SCHEMA_VERSION, writes that row to a file with no row, and refuses a file with "
            "any other rows without writing to it; there is no migration, and M3c's two tables are "
            "additive under version 1 (start creates them on any version-1 file). Written by "
```
REPLACE:
```
            "registry. Opened through the ConnectionFactory. Tables: schema_version, shadow_aggregates, "
            "shadow_samples, shadow_markers, from AD-1346 M3c shadow_parity and shadow_disagreements, and from "
            "AD-1346 M3d3b ticket_findings, ticket_samples, ticket_missing_samples and ticket_markers. "
            "start opens a file whose schema_version holds exactly "
            "one row of SCHEMA_VERSION, writes that row to a file with no row, and refuses a file with "
            "any other rows without writing to it; there is no migration, and M3c's two tables and M3d3b's "
            "four are additive under version 1 (start creates them on any version-1 file). Written by "
```

### 7.3 M1: `src/probos/admission/report.py`

**M1-17**

SEARCH:
```
``REPORT_QUERIES`` maps each frozen name to one SELECT. A later slice may add a name; none is
renamed or removed, so the queries the M4 ruling runs keep the names this slice gives them (#1604).
```
REPLACE:
```
``REPORT_QUERIES`` maps each frozen name to one SELECT. A later slice may add a name; none is
renamed or removed, so the queries the M4 ruling runs keep the names this slice gives them (#1604).
AD-1346 M3c appended ``parity_by_work_kind`` and ``disagreement_samples``, and AD-1346 M3d3b the five
``ticket_`` queries, which read the work-ticket tables; on a file without those tables they raise
``sqlite3.OperationalError``.
```

**M1-18**

SEARCH:
```
        "FROM shadow_disagreements ORDER BY seq DESC LIMIT ?"
    ),
})
```
REPLACE:
```
        "FROM shadow_disagreements ORDER BY seq DESC LIMIT ?"
    ),
    # AD-1346 M3d3b (D142): the work-ticket findings (since day), the two rings (limit), the markers and the days.
    "ticket_findings_by_operation": (
        "SELECT operation, code, work_kind, off_loop, SUM(findings) FROM ticket_findings WHERE day >= ? "
        "GROUP BY operation, code, work_kind, off_loop ORDER BY operation, code, work_kind, off_loop"
    ),
    "ticket_samples": (
        "SELECT seq, boot_id, hour, operation, code, work_kind, off_loop, finding_json FROM ticket_samples "
        "ORDER BY seq DESC LIMIT ?"
    ),
    "ticket_missing_samples": (
        "SELECT seq, boot_id, hour, operation, code, work_kind, off_loop, finding_json FROM ticket_missing_samples "
        "ORDER BY seq DESC LIMIT ?"
    ),
    "ticket_markers_by_boot": (
        "SELECT boot_id, MIN(hour), MAX(hour), SUM(offered), SUM(written), SUM(dropped), SUM(samples_dropped) "
        "FROM ticket_markers GROUP BY boot_id ORDER BY MIN(hour), boot_id"
    ),
    "ticket_days_recorded": "SELECT DISTINCT day FROM ticket_findings ORDER BY day",
})
```

### 7.4 M1: `tests/test_ad1346_admission_shadow_store.py`

**M1-19**

SEARCH:
```
- S1  a new file gets the six tables (AD-1346 M3c added two) and one ``schema_version`` row, and a restart adds no second row.
```
REPLACE:
```
- S1  a new file gets the ten tables (AD-1346 M3c added two, AD-1346 M3d3b four) and one ``schema_version`` row, and a restart adds no second row.
```

**M1-20**

SEARCH:
```
async def test_a_new_file_gets_six_tables_and_one_schema_version_row(tmp_path: Path) -> None:
    """S1 (kills ST-2 of the M3b campaign)."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    assert shadow.path == tmp_path / "data" / STORE_FILENAME and STORE_FILENAME == "admission_shadow.db"
    assert shadow.is_open is False
    await shadow.start()
    assert shadow.is_open is True
    await shadow.stop()
    assert shadow.is_open is False
    assert await rows(shadow.path, TABLES) == [
        ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",),
        ("shadow_parity",), ("shadow_samples",),
    ]
```
REPLACE:
```
async def test_a_new_file_gets_ten_tables_and_one_schema_version_row(tmp_path: Path) -> None:
    """S1 (kills ST-2 of the M3b campaign); AD-1346 M3d3b renamed it when the file gained its four ticket tables."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    assert shadow.path == tmp_path / "data" / STORE_FILENAME and STORE_FILENAME == "admission_shadow.db"
    assert shadow.is_open is False
    await shadow.start()
    assert shadow.is_open is True
    await shadow.stop()
    assert shadow.is_open is False
    assert await rows(shadow.path, TABLES) == [
        ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",),
        ("shadow_parity",), ("shadow_samples",), ("ticket_findings",), ("ticket_markers",),
        ("ticket_missing_samples",), ("ticket_samples",),
    ]
```

### 7.5 M1: `tests/test_ad1346_admission_shadow_parity.py`

**M1-21**

SEARCH:
```
- P6  a version-1 file with only M3b's three tables opens, keeps its rows and gains the two M3c tables.
```
REPLACE:
```
- P6  a version-1 file with only M3b's three tables opens, keeps its rows and gains the two M3c tables and AD-1346
      M3d3b's four.
```

**M1-22**

SEARCH:
```
async def test_a_version_1_file_with_m3bs_three_tables_opens_keeps_its_rows_and_gains_two(tmp_path: Path) -> None:
    """P6: D58's compatibility path (kills ST-5)."""
    path = tmp_path / "data" / STORE_FILENAME
    path.parent.mkdir(parents=True)
    db = await default_factory.connect(str(path))
    try:
        await db.executescript(M3B_FILE)
        await db.commit()
    finally:
        await db.close()
    assert await rows(path, TABLES) == [("schema_version",), ("shadow_aggregates",), ("shadow_markers",), ("shadow_samples",)]
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    await shadow.stop()
    assert await rows(path, TABLES) == [
        ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",),
        ("shadow_parity",), ("shadow_samples",),
    ]
```
REPLACE:
```
async def test_a_version_1_file_with_m3bs_three_tables_opens_keeps_its_rows_and_gains_the_later_tables(
    tmp_path: Path,
) -> None:
    """P6: D58's compatibility path (kills ST-5); AD-1346 M3d3b renamed it when the file gained four more tables."""
    path = tmp_path / "data" / STORE_FILENAME
    path.parent.mkdir(parents=True)
    db = await default_factory.connect(str(path))
    try:
        await db.executescript(M3B_FILE)
        await db.commit()
    finally:
        await db.close()
    assert await rows(path, TABLES) == [("schema_version",), ("shadow_aggregates",), ("shadow_markers",), ("shadow_samples",)]
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    await shadow.stop()
    assert await rows(path, TABLES) == [
        ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",),
        ("shadow_parity",), ("shadow_samples",), ("ticket_findings",), ("ticket_markers",),
        ("ticket_missing_samples",), ("ticket_samples",),
    ]
```

### 7.6 M1: `tests/test_ad1346_admission_shadow_report.py`

**M1-23**

SEARCH:
```
    assert tuple(REPORT_QUERIES) == (
        "decisions_by_work_kind", "latency_by_work_kind", "would_refuse_samples", "markers_by_boot",
        "days_recorded", "schema_version", "parity_by_work_kind", "disagreement_samples",
    )
```
REPLACE:
```
    assert tuple(REPORT_QUERIES) == (
        "decisions_by_work_kind", "latency_by_work_kind", "would_refuse_samples", "markers_by_boot",
        "days_recorded", "schema_version", "parity_by_work_kind", "disagreement_samples",
        "ticket_findings_by_operation", "ticket_samples", "ticket_missing_samples", "ticket_markers_by_boot",
        "ticket_days_recorded",
    )
```

### 7.7 M1: `tests/test_ad1346_admission_service.py` (an M3d3a-edited file)

**M1-24**

SEARCH:
```
    "store.py": {
        "__future__", "dataclasses", "datetime", "json", "logging", "pathlib", "typing", "probos.admission.record",
        "probos.protocols", "probos.storage.sqlite_factory",
    },
```
REPLACE:
```
    "store.py": {
        "__future__", "dataclasses", "datetime", "hashlib", "json", "logging", "pathlib", "re", "typing",
        "probos.admission.record", "probos.admission.tickets", "probos.protocols", "probos.storage.sqlite_factory",
    },
```

**M1-25**

SEARCH:
```
    await and open a store. AD-1346 M3d3a added ``asyncio`` to ``service.py``'s allowlist, for ``get_running_loop`` and
    ``call_soon_threadsafe``, neither of which awaits."""
```
REPLACE:
```
    await and open a store. AD-1346 M3d3a added ``asyncio`` to ``service.py``'s allowlist, for ``get_running_loop`` and
    ``call_soon_threadsafe``, neither of which awaits. AD-1346 M3d3b added ``hashlib``, ``re`` and
    ``probos.admission.tickets`` to ``store.py``'s."""
```

### 7.8 (no further pairs in M1)

### 7.9 (no pairs in M2 besides the new file)

### 7.10.N New file: `tests/test_ad1346_admission_ticket_record.py` (M2)

```python
"""AD-1346 M3d3b1 (#1604): the work ticket's persisted record, four tables in ``admission_shadow.db``, over real
SQLite in ``tmp_path``.

``AdmissionShadowStore.write_batch`` writes a batch's work-ticket part (``TicketBatch``) in the transaction of its
verdicts: finding counts per (UTC day, operation, code, work kind, ``off_loop``), two sample rings (the batch's
``missing`` samples in ``ticket_missing_samples``, its other samples in ``ticket_samples``) and marker rows per (boot,
UTC hour); ``prune`` bounds the counts and the markers. In ``src`` the recorder, the one caller of ``write_batch``,
builds each batch without a work-ticket part, so that part is the empty default until AD-1346 M3d3b2 adds the
recorder's offers. The tests that write the part build it directly, with findings from a real ``TicketRegistry``
over a real ``AgentStopService`` under ``tmp_path`` or built as ``TicketFinding`` values, and read it back with SQL
or with the report's queries.

- TR1 a new file gets the four ticket tables beside the six earlier ones, each with its columns, NOT NULL and key.
- TR2 a batch adds finding counts by UTC day and writes each ring's sample as ``persisted_finding`` JSON, with the raw
      ticket id in no ring row; its marker rows hold the batch's offered, dropped and samples-dropped counts and the
      findings it wrote; it adds no verdict marker and returns 0, and a second write adds to each count and marker row.
- TR3 each ring keeps at most its own size of its newest rows, and a write to the missing ring alone leaves the other.
- TR4 a batch whose write fails on a NULL boot id is rolled back: a later commit lands none of its ticket rows.
- TR5 ``prune`` deletes the finding days and marker hours before the window and then the oldest markers beyond
      ``MARKER_ROW_LIMIT``; it leaves the rings, and the counts it returns leave the work-ticket rows out.
- TR6 the ring sizes and the digest length are named constants, and 35 days of the ticket key space stay below
      ``AGGREGATE_ROW_LIMIT``.
- TR7 on a version-1 file without the ticket tables each ``ticket_`` report query raises ``sqlite3.OperationalError``
      on a read-only connection; ``start`` then keeps the file's rows and adds the tables.
- TR8 the five ``ticket_`` report queries answer on a ``mode=ro`` connection to a store two boots wrote: the findings
      counted per (operation, code, work kind, ``off_loop``), each ring's newest sample first and one marker row per
      boot, with the marker rows of hours that have only a dropped or only a samples-dropped count; a delete on it
      raises.
- TR9 ``persisted_finding`` shows the ticket and parent ids as ``ticket_digest`` in their fields and, where they have
      the registry's form (32 lowercase hex characters), at each place in the cause; an id of 16, 31 or 33 lowercase
      hex characters, or of 32 characters one of which is not lowercase hex (each other printable ASCII character
      and an Arabic-Indic digit), stays in the cause as it is; each id is looked for on its own; and every other
      value, the stop's id included, is the finding's. ``ticket_digest`` is ``""`` for ``""`` and otherwise SHA-256
      over UTF-8, cut to ``TICKET_DIGEST_CHARS``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from probos.admission import store as store_module
from probos.admission.report import REPORT_QUERIES, open_read_only, run_query
from probos.admission.store import (
    AGGREGATE_RETENTION_DAYS,
    AGGREGATE_ROW_LIMIT,
    DAY_SECONDS,
    SCHEMA_VERSION,
    TICKET_DIGEST_CHARS,
    TICKET_MISSING_RING_SIZE,
    TICKET_SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    TicketBatch,
    TicketSample,
    persisted_finding,
    ticket_digest,
    utc_hour,
)
from probos.admission.taxonomy import SEAM_MODEL_CALL, TICKET_REASON_CODES, WORK_KINDS
from probos.admission.tickets import (
    TICKET_EFFECTS,
    TICKET_FINDING_KEYS,
    TICKET_OPERATIONS,
    TicketBudget,
    TicketFinding,
    TicketRegistry,
    TicketScope,
)
from probos.agent_stop import AgentStopService
from probos.storage.sqlite_factory import default_factory
from tests.fixtures.ad1346_shadow import HOUR, T0, rows

BOOT = "boot-a"
AGENT = "ad1346-m3d3b1-agent"
DAY = "2026-10-28"
TABLES = "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
SHADOW_TABLES = [
    ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",), ("shadow_parity",),
    ("shadow_samples",),
]
TICKET_TABLE_NAMES = [("ticket_findings",), ("ticket_markers",), ("ticket_missing_samples",), ("ticket_samples",)]
SAMPLE_COLUMNS = ["seq", "boot_id", "hour", "recorded_at", "operation", "code", "work_kind", "off_loop", "finding_json"]
#: (table, its columns in order, its primary key's columns in key order).
TICKET_TABLES = (
    (
        "ticket_findings",
        ["day", "operation", "code", "work_kind", "off_loop", "findings"],
        ["day", "operation", "code", "work_kind", "off_loop"],
    ),
    ("ticket_samples", SAMPLE_COLUMNS, ["seq"]),
    ("ticket_missing_samples", SAMPLE_COLUMNS, ["seq"]),
    ("ticket_markers", ["boot_id", "hour", "offered", "written", "dropped", "samples_dropped"], ["boot_id", "hour"]),
)
FINDINGS = (
    "SELECT day, operation, code, work_kind, off_loop, findings FROM ticket_findings "
    "ORDER BY operation, code, work_kind, off_loop"
)
MARKERS = "SELECT boot_id, hour, offered, written, dropped, samples_dropped FROM ticket_markers ORDER BY hour"
SAMPLE_READ = "boot_id, hour, recorded_at, operation, code, work_kind, off_loop, finding_json"
#: The ``ticket_`` report queries and the parameters each takes.
TICKET_QUERIES = {
    "ticket_findings_by_operation": (DAY,), "ticket_samples": (1,), "ticket_missing_samples": (1,),
    "ticket_markers_by_boot": (), "ticket_days_recorded": (),
}
_SCOPE = TicketScope(frozenset(TICKET_EFFECTS))


def _with_tickets(tickets: TicketBatch) -> ShadowBatch:
    """A batch whose verdict part is empty."""
    return ShadowBatch({}, [], {}, {}, {}, tickets=tickets)


def _missing() -> TicketFinding:
    return TicketFinding(SEAM_MODEL_CALL, "ticket_missing", "No ticket was presented at model_call.", presented_key=AGENT)


def _unknown() -> TicketFinding:
    return TicketFinding("tool", "ticket_unknown", "The presented object is not a ticket the registry holds.")


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[AdmissionShadowStore]:
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        yield shadow
    finally:
        await shadow.stop()


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


async def test_a_new_file_gets_the_four_ticket_tables_with_their_columns_and_keys(store: AdmissionShadowStore) -> None:
    """TR1 (kills TRX-1)."""
    assert await rows(store.path, TABLES) == sorted(SHADOW_TABLES + TICKET_TABLE_NAMES)
    for table, columns, key in TICKET_TABLES:
        info = await rows(store.path, f"PRAGMA table_info({table})")
        assert [column[1] for column in info] == columns, table
        assert [column[1] for column in sorted(info, key=lambda column: column[5]) if column[5]] == key, table
        assert all(column[3] == 1 for column in info if column[1] != "seq"), table
    assert await rows(store.path, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]


async def test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers(
    store: AdmissionShadowStore, stops: AgentStopService,
) -> None:
    """TR2 (kills TRX-2, TRX-3, TRX-5, TRX-8, TRX-17): findings from a real registry under a real Captain's stop."""
    registry = TicketRegistry(stops, max_depth=1, clock=lambda: 1_000.0)
    issued = registry.issue(
        principal_key=AGENT, work_kind="agentic_run", seam="agentic_run", scope=_SCOPE, budget=TicketBudget(),
    )
    assert issued.ticket is not None, "premise: the registry issued the ticket"
    raw = issued.ticket.ticket_id
    missing = registry.check(None, effect=SEAM_MODEL_CALL, presented_key=AGENT)
    stop = await stops.issue_stop(AGENT, reason="ad1346-m3d3b1: a stop whose finding a ring keeps")
    revoked = registry.check(issued.ticket, effect=SEAM_MODEL_CALL, presented_key=AGENT)
    assert (missing.code, revoked.code, revoked.stop_id) == ("ticket_missing", "ticket_revoked", stop.record.stop_id)
    assert raw in revoked.cause, "premise: the registry's cause names the ticket's id"
    first, second = utc_hour(T0), utc_hour(T0 + HOUR)
    batch = _with_tickets(TicketBatch(
        findings={
            (first, "issue", "ticket_issued", "agentic_run", False): 1,
            (first, "tool", "ticket_live", "agentic_run", False): 2,
            (first, "model_call", "ticket_missing", "", True): 3,
            (second, "model_call", "ticket_revoked", "agentic_run", False): 1,
        },
        samples=[TicketSample(second, T0 + HOUR, revoked, False)],
        missing=[TicketSample(first, T0, missing, True)],
        offered={first: 6, second: 2},
        dropped={second: 1},
        samples_dropped={first: 1},
    ))
    assert await store.write_batch(BOOT, batch) == 0, "the number returned counts verdicts only"
    assert await rows(store.path, FINDINGS) == [
        (DAY, "issue", "ticket_issued", "agentic_run", 0, 1),
        (DAY, "model_call", "ticket_missing", "", 1, 3),
        (DAY, "model_call", "ticket_revoked", "agentic_run", 0, 1),
        (DAY, "tool", "ticket_live", "agentic_run", 0, 2),
    ]
    assert await rows(store.path, MARKERS) == [(BOOT, first, 6, 6, 0, 1), (BOOT, second, 2, 1, 1, 0)]
    assert await rows(store.path, "SELECT COUNT(*) FROM shadow_markers") == [(0,)], "no verdict marker is added"
    kept = await rows(store.path, f"SELECT {SAMPLE_READ} FROM ticket_samples")
    assert [row[:7] for row in kept] == [(BOOT, second, T0 + HOUR, "model_call", "ticket_revoked", "agentic_run", 0)]
    body = json.loads(kept[0][7])
    assert list(body) == list(TICKET_FINDING_KEYS) and body == persisted_finding(revoked)
    assert kept[0][7] == json.dumps(body, separators=(",", ":")), "the ring keeps compact JSON"
    assert (body["ticket_id"], body["stop_id"], body["principal_key"]) == (ticket_digest(raw), stop.record.stop_id, AGENT)
    noted = await rows(store.path, f"SELECT {SAMPLE_READ} FROM ticket_missing_samples")
    assert [row[:7] for row in noted] == [(BOOT, first, T0, "model_call", "ticket_missing", "", 1)]
    assert json.loads(noted[0][7]) == missing.to_dict(), "a finding with no ticket id is kept as it is"
    assert all(raw not in row[7] for row in kept + noted), "the raw ticket id is in no ring row"
    assert await store.write_batch(BOOT, batch) == 0
    assert [row[-1] for row in await rows(store.path, FINDINGS)] == [2, 6, 2, 4], "a second write adds to each row"
    assert await rows(store.path, MARKERS) == [(BOOT, first, 12, 12, 0, 2), (BOOT, second, 4, 2, 2, 0)]


async def test_the_two_ticket_rings_each_keep_their_newest_rows(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TR3 (kills TRX-4, TRX-6, TRX-7)."""
    monkeypatch.setattr(store_module, "TICKET_SAMPLE_RING_SIZE", 2)
    monkeypatch.setattr(store_module, "TICKET_MISSING_RING_SIZE", 3)
    others_read = "SELECT recorded_at FROM ticket_samples ORDER BY seq"
    missing_read = "SELECT recorded_at FROM ticket_missing_samples ORDER BY seq"
    hour = utc_hour(T0)
    others = [TicketSample(hour, T0 + n, _unknown(), False) for n in range(3)]
    missing = [TicketSample(hour, T0 + n, _missing(), False) for n in range(8)]
    await store.write_batch(BOOT, _with_tickets(TicketBatch(samples=others[:1], missing=missing[:4])))
    await store.write_batch(BOOT, _with_tickets(TicketBatch(samples=others[1:], missing=missing[4:5])))
    assert await rows(store.path, others_read) == [(T0 + 1,), (T0 + 2,)]
    assert await rows(store.path, missing_read) == [(T0 + 2,), (T0 + 3,), (T0 + 4,)]
    await store.write_batch(BOOT, _with_tickets(TicketBatch(missing=missing[5:])))
    assert await rows(store.path, others_read) == [(T0 + 1,), (T0 + 2,)], "a write to one ring leaves the other"
    assert await rows(store.path, missing_read) == [(T0 + 5,), (T0 + 6,), (T0 + 7,)]


async def test_a_failed_batch_rolls_back_its_ticket_rows_and_a_later_commit_does_not_land_them(
    store: AdmissionShadowStore,
) -> None:
    """TR4: a NULL boot id fails the batch's write (the shape of S4)."""
    hour = utc_hour(T0)
    failing = TicketBatch(
        findings={(hour, "tool", "ticket_live", "agentic_run", False): 5},
        missing=[TicketSample(hour, T0, _missing(), False)],
        offered={hour: 5},
    )
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        await store.write_batch(None, _with_tickets(failing))  # type: ignore[arg-type]
    later = TicketBatch(findings={(hour, "tool", "ticket_live", "agentic_run", False): 1}, offered={hour: 1})
    assert await store.write_batch(BOOT, _with_tickets(later)) == 0
    assert await rows(store.path, "SELECT findings FROM ticket_findings") == [(1,)]
    assert await rows(store.path, "SELECT COUNT(*) FROM ticket_missing_samples") == [(0,)]
    assert await rows(store.path, "SELECT boot_id, offered, written FROM ticket_markers") == [(BOOT, 1, 1)]


async def test_prune_deletes_old_ticket_days_and_markers_and_leaves_the_rings(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TR5 (kills TRX-9, TRX-10, TRX-11, TRX-21)."""
    old, kept, today = utc_hour(T0 - 35 * DAY_SECONDS), utc_hour(T0 - 34 * DAY_SECONDS), utc_hour(T0)
    assert (old, kept) == ("2026-09-23T12", "2026-09-24T12")  # premise
    findings = {(hour, "tool", "ticket_live", "agentic_run", False): 1 for hour in (old, kept, today)}
    at = T0 - 35 * DAY_SECONDS
    stale = TicketBatch(
        findings=findings,
        samples=[TicketSample(old, at, _unknown(), False)],
        missing=[TicketSample(old, at, _missing(), False)],
    )
    await store.write_batch(BOOT, _with_tickets(stale))
    assert await store.prune(T0) == (0, 0), "the counts prune returns leave the work-ticket rows out"
    assert await rows(store.path, "SELECT day FROM ticket_findings ORDER BY day") == [("2026-09-24",), (DAY,)]
    assert await rows(store.path, "SELECT hour FROM ticket_markers ORDER BY hour") == [(kept,), (today,)]
    rings = "SELECT (SELECT COUNT(*) FROM ticket_samples), (SELECT COUNT(*) FROM ticket_missing_samples)"
    assert await rows(store.path, rings) == [(1, 1)], "neither ring is pruned by day"
    await store.write_batch("boot-0", _with_tickets(TicketBatch(offered={today: 1})))
    monkeypatch.setattr(store_module, "MARKER_ROW_LIMIT", 2)
    assert await store.prune(T0) == (0, 0)
    remaining = await rows(store.path, "SELECT boot_id, hour FROM ticket_markers ORDER BY boot_id")
    assert remaining == [("boot-0", today), (BOOT, today)], "the oldest hour goes first, whichever boot wrote it"


def test_the_ticket_key_space_and_the_rings_are_bounded_by_named_constants() -> None:
    """TR6: D139's bounds."""
    assert (TICKET_SAMPLE_RING_SIZE, TICKET_MISSING_RING_SIZE, TICKET_DIGEST_CHARS, SCHEMA_VERSION) == (5_000, 1_000, 16, 1)
    one_day = len(TICKET_OPERATIONS) * len(TICKET_REASON_CODES) * (len(WORK_KINDS) + 1) * 2
    assert one_day * AGGREGATE_RETENTION_DAYS < AGGREGATE_ROW_LIMIT, one_day


async def test_a_file_without_the_ticket_tables_keeps_its_rows_and_gains_them_at_start(tmp_path: Path) -> None:
    """TR7: D143. The file is this build's with its four ticket tables dropped, which leaves the tables AD-1346 M3c's
    store creates."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        verdicts = {(utc_hour(T0), "intent", "intent", "admit", "admitted", 3): 9}
        await shadow.write_batch(BOOT, ShadowBatch(verdicts, [], {}, {}, {}))
    finally:
        await shadow.stop()
    db = await default_factory.connect(str(shadow.path))
    try:
        await db.executescript("".join(f"DROP TABLE {name};" for (name,) in TICKET_TABLE_NAMES))
        await db.commit()
    finally:
        await db.close()
    assert await rows(shadow.path, TABLES) == SHADOW_TABLES, "premise: the tables AD-1346 M3c's store creates"
    assert tuple(name for name in REPORT_QUERIES if name.startswith("ticket_")) == tuple(TICKET_QUERIES)
    reader = await open_read_only(shadow.path)
    try:
        for name, params in TICKET_QUERIES.items():
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                await run_query(reader, name, params)
        assert await run_query(reader, "days_recorded") == [(DAY,)]
    finally:
        await reader.close()
    again = AdmissionShadowStore(data_dir=tmp_path / "data")
    await again.start()
    await again.stop()
    assert await rows(shadow.path, TABLES) == sorted(SHADOW_TABLES + TICKET_TABLE_NAMES)
    assert await rows(shadow.path, "SELECT * FROM shadow_aggregates") == [(DAY, "intent", "intent", "admit", "admitted", 3, 9)]
    assert await rows(shadow.path, "SELECT version FROM schema_version") == [(1,)]


async def test_the_ticket_queries_answer_on_a_read_only_connection(tmp_path: Path) -> None:
    """TR8 (kills TRX-18, TRX-19, TRX-22): for each of operation, code, work kind and ``off_loop``, two findings
    differ in it alone. A second boot, ``boot-0``, writes only a dropped and a samples-dropped count, at two different
    hours. Its id sorts before ``boot-a`` and its first hour after ``boot-a``'s, so the order by hour puts ``boot-a``
    first and the order by id would not."""
    first, second, third = utc_hour(T0), utc_hour(T0 + DAY_SECONDS), utc_hour(T0 + DAY_SECONDS + HOUR)
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        await shadow.write_batch(BOOT, _with_tickets(TicketBatch(
            findings={
                (first, "tool", "ticket_live", "agentic_run", False): 2,
                (second, "tool", "ticket_live", "agentic_run", False): 1,
                (second, "tool", "ticket_live", "agentic_run", True): 1,
                (second, "tool", "ticket_live", "", True): 1,
                (second, "tool", "ticket_missing", "", True): 1,
                (second, "model_call", "ticket_missing", "", True): 1,
            },
            samples=[TicketSample(first, T0, _unknown(), False), TicketSample(first, T0 + 1, _unknown(), True)],
            missing=[
                TicketSample(second, T0 + DAY_SECONDS, _missing(), True),
                TicketSample(second, T0 + DAY_SECONDS + 1, _missing(), False),
            ],
            offered={first: 2, second: 6},
            dropped={second: 1},
        )))
        await shadow.write_batch("boot-0", _with_tickets(TicketBatch(dropped={second: 1}, samples_dropped={third: 1})))
    finally:
        await shadow.stop()
    reader = await open_read_only(shadow.path)
    try:
        assert await run_query(reader, "ticket_findings_by_operation", (DAY,)) == [
            ("model_call", "ticket_missing", "", 1, 1), ("tool", "ticket_live", "", 1, 1),
            ("tool", "ticket_live", "agentic_run", 0, 3), ("tool", "ticket_live", "agentic_run", 1, 1),
            ("tool", "ticket_missing", "", 1, 1),
        ]
        assert await run_query(reader, "ticket_findings_by_operation", ("2026-10-29",)) == [
            ("model_call", "ticket_missing", "", 1, 1), ("tool", "ticket_live", "", 1, 1),
            ("tool", "ticket_live", "agentic_run", 0, 1), ("tool", "ticket_live", "agentic_run", 1, 1),
            ("tool", "ticket_missing", "", 1, 1),
        ]
        assert await run_query(reader, "ticket_findings_by_operation", ("2026-10-30",)) == []
        newest = await run_query(reader, "ticket_samples", (1,))
        assert [row[3:7] for row in newest] == [("tool", "ticket_unknown", "", 1)], "the newest sample first"
        noted = await run_query(reader, "ticket_missing_samples", (1,))
        assert [row[3:7] for row in noted] == [("model_call", "ticket_missing", "", 0)], "the newest sample first"
        assert await run_query(reader, "ticket_markers_by_boot") == [
            (BOOT, first, second, 8, 7, 1, 0), ("boot-0", second, third, 0, 0, 1, 1),
        ]
        assert await run_query(reader, "ticket_days_recorded") == [(DAY,), ("2026-10-29",)]
        with pytest.raises(sqlite3.OperationalError):
            await reader.execute("DELETE FROM ticket_findings")
    finally:
        await reader.close()


def test_a_persisted_finding_shows_ticket_ids_only_as_digests() -> None:
    """TR9 (kills TRX-12, TRX-13, TRX-14, TRX-15, TRX-16, TRX-20)."""
    ticket, parent, stop = "0123456789abcdef" * 2, "fedcba9876543210" * 2, "ef" * 16
    finding = TicketFinding(
        "model_call", "ticket_revoked",
        f"Ticket {ticket} of a child of {parent} is under the Captain's stop {stop}; ticket {ticket} is revoked.",
        ticket_id=ticket, principal_key="agent", presented_key="agent", parent_id=parent, depth=1,
        work_kind="delegated_task", stop_id=stop,
    )
    body = persisted_finding(finding)
    assert list(body) == list(TICKET_FINDING_KEYS)
    assert (body["ticket_id"], body["parent_id"], body["stop_id"]) == (ticket_digest(ticket), ticket_digest(parent), stop)
    assert body["cause"] == (
        f"Ticket {ticket_digest(ticket)} of a child of {ticket_digest(parent)} is under the Captain's stop {stop}; "
        f"ticket {ticket_digest(ticket)} is revoked."
    )
    same = ("operation", "code", "principal_key", "presented_key", "depth", "work_kind", "stop_id")
    assert {name: body[name] for name in same} == {name: finding.to_dict()[name] for name in same}
    short = TicketFinding("tool", "ticket_unknown", "The presented object is not a ticket the registry holds.", ticket_id="T")
    assert persisted_finding(short)["cause"] == short.cause, "an id not of the issued form is not looked for in the cause"
    lowercase_hex = "0123456789abcdef"
    odd_ids = ["ab" * 8, "a" * 31, "a" * 33, "\u0661" + "a" * 31]
    odd_ids += [char + "a" * 31 for char in map(chr, range(32, 127)) if char not in lowercase_hex]
    for odd in odd_ids:
        other = TicketFinding("tool", "ticket_unknown", f"The presented id {odd} is unknown.", ticket_id=odd)
        assert persisted_finding(other)["cause"] == other.cause, f"{odd!r} is not of the issued form"
    upper = "AB" * 16
    mixed = TicketFinding(
        "tool", "ticket_unknown", f"The id {upper} names {parent}.", ticket_id=upper, parent_id=parent,
    )
    assert persisted_finding(mixed)["cause"] == f"The id {upper} names {ticket_digest(parent)}.", "each id alone"
    assert persisted_finding(short)["ticket_id"] == ticket_digest("T")
    assert ticket_digest("") == "" and ticket_digest(ticket) == hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]
    accented = "ticket-\u00e9"
    assert ticket_digest(accented) == hashlib.sha256(accented.encode("utf-8")).hexdigest()[:16], "over UTF-8"
    assert len(ticket_digest("T")) == TICKET_DIGEST_CHARS == 16
```

## 8. Tracking (M3's commit)

**Date rule.** If M3 is committed on a date other than 2026-10-30, the Builder substitutes the commit date for `2026-10-30` in exactly two strings, both new:
- the new paragraph's head `**AD-1346 (2026-10-30), #1604 M3d3b1 -- ` in M3-01's REPLACE;
- the new heading `### AD-1346 M3d3b1 -- the work ticket's persisted record: four tables in admission_shadow.db (2026-10-30, #1604)` in M3-02's REPLACE.

M3-01's SEARCH text and the M3d3a head its REPLACE keeps must be M3d3a's head as merged. If M3d3a's own date rule gave it another date, use that date in both. The commit date is the committing machine's local date when M3 is committed, not the UTC date. No other deviation is permitted.

Then regenerate the ledger with `python -P scripts/gen_ad_ledger.py` (write mode), and commit `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. Two bullets for `DECISIONS.md` are added in a later docs commit, after the reviewed commit: the campaign of record, and D143's executed older-build check with its printed results.

**Where the entries land.**
- M3-01 puts the new paragraph between the title line `# ProbOS Progress` and M3d3a's paragraph (`PROGRESS.md:3` on `60440cb2`). `PROGRESS.md` runs newest first.
- M3-02 puts M3d3b1's entry (its heading, paragraph and bullets, the last of them its `*Reversal.*` bullet, then a blank line) directly above the heading that follows M3d3a's entry, `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)` (`DECISIONS.md:1036` on `60440cb2`). M3d3b1's entry therefore follows M3d3a's (`:1023`), and the AD-1346 entries run oldest first. M3d3a's later docs bullets go inside its own entry, above that heading, so this anchor holds.
- Neither new head carries a status keyword of `scripts/gen_ad_ledger.py:126-132` in its first 120 characters (`:139`).

**M3-01** (`PROGRESS.md`)

SEARCH:
```
# ProbOS Progress

**AD-1346 (2026-10-30), #1604 M3d3a -- 
```
REPLACE:
```
# ProbOS Progress

**AD-1346 (2026-10-30), #1604 M3d3b1 -- the work ticket's persisted record: four tables in `admission_shadow.db`.** `AdmissionShadowStore` gains `ticket_findings` (finding counts per UTC day, operation, code, work kind and `off_loop`), two sample rings (`ticket_samples`, at most the newest 5,000, and `ticket_missing_samples`, at most the newest 1,000, for a batch's `missing` samples) and `ticket_markers` (offered, written, dropped and samples dropped per boot and UTC hour), all additive under schema version 1. `write_batch` writes a batch's work-ticket part (`TicketBatch`) in the transaction of its verdicts; a ring row holds `TicketFinding.to_dict()` as JSON with the ticket and parent ids shown as a 16-character SHA-256 digest; `prune` deletes finding days and marker rows with the existing retention constants and `MARKER_ROW_LIMIT`. `probos.admission.report` appends five `ticket_` queries. Nothing in `src` fills the work-ticket part yet: the recorder builds each batch without one, so on a vessel the tables stay empty until M3d3b2 adds the recorder's offers at the sink check and at the issue. A build without the tables opens, writes, prunes and queries a file this build wrote, and none of its statements names the four (D143, executed against the M3c store). The contract is `prompts/ad-1346-m3d3b1-ticket-record-store.md`.

**AD-1346 (2026-10-30), #1604 M3d3a -- 
```

**M3-02** (`DECISIONS.md`)

SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1346 M3d3b1 -- the work ticket's persisted record: four tables in admission_shadow.db (2026-10-30, #1604)

AD-1346 M3d3b1 adds the tables, writes, bounds and report queries of the work ticket's persisted record to `admission_shadow.db`, the first of two M3d3b slices. Nothing in `src` fills them yet: M3d3b2 adds the recorder's offers at the sink check and at the issue, the chain test from a sink to a report query and the cost with the recorder. It prepares the service-written record and markers of #1604 property 8 and the persisted evidence of properties 3 and 5. The contract is `prompts/ad-1346-m3d3b1-ticket-record-store.md`.

- *D137 (the split).* The store, its declaration and the report first; the writer's offers second. Rejected: one slice (about forty pairs and two test files by the contract's estimate), and the offers first (no table to write to).
- *D138, D144 (what is kept).* M3d3b2's offers are to count every finding, to sample none of `ticket_issued` and `ticket_live`, and to put `ticket_missing` samples in a ring of their own, so that they do not push the rarer findings out of the other; the store writes what a batch holds and does not read a sample's code to choose its ring. A ring row is `TicketFinding.to_dict()` with the ticket and parent ids shown as a 16-character SHA-256 digest, as OWASP ASVS 4 (requirement 7.1.1) asks for session tokens in logs. Rejected: one ring for every sampled code, and raw ids.
- *D139 (bounds).* For keys whose work kind is in `WORK_KINDS` or empty and whose `off_loop` is a bool (the store checks neither; M3d3b2's offer is to, D140 and register R53), at most 3 x 12 x 13 x 2 = 936 finding rows a day for this tree's vocabularies, 32,760 over the 35-day window, below `AGGREGATE_ROW_LIMIT`; rings of 5,000 and 1,000; markers bounded as the verdict markers are.
- *D140 (the writer, binding on M3d3b2).* The existing recorder, in the flush transaction of the verdicts, offered from `_check_ticket` (on the service's loop when the service has one) and from `hold` before it sets the carrier. Rejected: a second writer on the same file.
- *D141 (markers).* A new `ticket_markers` table. Rejected: columns on `shadow_markers`, which need `ALTER TABLE`.
- *D143 (compatibility).* Schema version 1 stays and the four tables are additive: a build without them opens, writes, prunes and queries a file this build wrote without naming them in any statement (executed against the M3c store); the `ticket_` queries raise on a file without them. Rejected: version 2, under which an older build would refuse the file.
- *D147 (the clock).* From M3d3b2's deploy, a fix that changes which findings are kept, or under which key, restarts the 7 days for the sink records; a fix to a report query, the markers or the digest does not.
- *Tests.* One new file (`tests/test_ad1346_admission_ticket_record.py`, TR1 to TR9); the store's table list (S1), P6, the report's names (Q1) and T14's `store.py` allowlist are updated.
- *Residual, accepted.* Register R52 to R57 of the contract.
- *Reversal.* Revert the M3d3b1 commits. A file this build started keeps its four tables, which no statement of a build without them names (D143).

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

## 9. What this does NOT change

- The five existing tables' DDL, keys and statements, `SCHEMA_VERSION`, `start`'s version check, and `store.py`'s other existing constants and their values (`_SCHEMA` gains the four `CREATE TABLE`s).
- `write_batch`'s and `prune`'s return values and the order of their existing statements.
- `ShadowRecorder` (`recorder.py`), `COUNTER_NAMES`, `AdmissionService` (`service.py`), `seam.py`, `carrier.py`, `tickets.py`, `taxonomy.py`, `record.py`, `TICKET_FINDING_KEYS`.
- The existing `REPORT_QUERIES` names and SQL, `run_query`, `open_read_only`, `p99_bucket`.
- The declaration's id, owner, criticality, retention, backup and restore; `docs/development/store-baseline.yaml`; `docs/development/architecture-baseline.yaml`.
- `runtime.py`, `startup/*`, `config.py`, `config/system.yaml`, every sink and entry, every `shadow_at`, `hold_at` and `check_at` call.

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline passes; run on the Captain's Windows host)

Group and its `--tests`: every TRX row runs against `tests/test_ad1346_admission_ticket_record.py`. No two rows mutate the same line. Each Line is a stripped line that occurs once in its file at M1's tree and at M2's tree. No row is expected to be equivalent.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| TRX-1 | M1 | `src/probos/admission/store.py` | `PRIMARY KEY (day, operation, code, work_kind, off_loop)` | `PRIMARY KEY (day, operation, code, work_kind)` | `test_a_new_file_gets_the_four_ticket_tables_with_their_columns_and_keys` |
| TRX-2 | M1 | `src/probos/admission/store.py` | `ticket_findings.append((hour[:10], operation, code, work_kind, int(off_loop), count))` | `ticket_findings.append((hour, operation, code, work_kind, int(off_loop), count))` | `test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers` |
| TRX-3 | M1 | `src/probos/admission/store.py` | `ticket_written[hour] = ticket_written.get(hour, 0) + count` | `pass` | `test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers` |
| TRX-4 | M1 | `src/probos/admission/store.py` | `ticket_missing = [_ticket_sample_row(boot_id, sample) for sample in tickets.missing]` | `ticket_missing = []` | `test_the_two_ticket_rings_each_keep_their_newest_rows` |
| TRX-5 | M1 | `src/probos/admission/store.py` | `await db.executemany(_UPSERT_TICKET_FINDING, ticket_findings)` | `pass` | `test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers` |
| TRX-6 | M1 | `src/probos/admission/store.py` | `await db.execute(_TRIM_TICKET_SAMPLES, (TICKET_SAMPLE_RING_SIZE,))` | `pass` | `test_the_two_ticket_rings_each_keep_their_newest_rows` |
| TRX-7 | M1 | `src/probos/admission/store.py` | `await db.execute(_TRIM_TICKET_MISSING, (TICKET_MISSING_RING_SIZE,))` | `pass` | `test_the_two_ticket_rings_each_keep_their_newest_rows` |
| TRX-8 | M1 | `src/probos/admission/store.py` | `await db.executemany(_UPSERT_TICKET_MARKER, ticket_markers)` | `pass` | `test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers` |
| TRX-9 | M1 | `src/probos/admission/store.py` | `await db.execute(_PRUNE_TICKET_FINDINGS, (utc_day(now - (AGGREGATE_RETENTION_DAYS - 1) * DAY_SECONDS),))` | `pass` | `test_prune_deletes_old_ticket_days_and_markers_and_leaves_the_rings` |
| TRX-10 | M1 | `src/probos/admission/store.py` | `await db.execute(_PRUNE_TICKET_MARKERS, (utc_day(now - (MARKER_RETENTION_DAYS - 1) * DAY_SECONDS),))` | `pass` | `test_prune_deletes_old_ticket_days_and_markers_and_leaves_the_rings` |
| TRX-11 | M1 | `src/probos/admission/store.py` | `await db.execute(_DELETE_OLDEST_TICKET_MARKERS, (count - MARKER_ROW_LIMIT,))` | `pass` | `test_prune_deletes_old_ticket_days_and_markers_and_leaves_the_rings` |
| TRX-12 | M1 | `src/probos/admission/store.py` | `body["ticket_id"] = ticket_digest(finding.ticket_id)` | `pass` | `test_a_persisted_finding_shows_ticket_ids_only_as_digests` |
| TRX-13 | M1 | `src/probos/admission/store.py` | `body["parent_id"] = ticket_digest(finding.parent_id)` | `pass` | `test_a_persisted_finding_shows_ticket_ids_only_as_digests` |
| TRX-14 | M1 | `src/probos/admission/store.py` | `cause = cause.replace(raw, ticket_digest(raw))` | `pass` | `test_a_persisted_finding_shows_ticket_ids_only_as_digests` |
| TRX-15 | M1 | `src/probos/admission/store.py` | `_ISSUED_ID: Final = re.compile(r"[0-9a-f]{32}")` | `_ISSUED_ID: Final = re.compile(r"[0-9a-f]+")` | `test_a_persisted_finding_shows_ticket_ids_only_as_digests` |
| TRX-16 | M1 | `src/probos/admission/store.py` | `return hashlib.sha256(value.encode("utf-8")).hexdigest()[:TICKET_DIGEST_CHARS] if value else ""` | `return value` | `test_a_persisted_finding_shows_ticket_ids_only_as_digests` |
| TRX-17 | M1 | `src/probos/admission/store.py` | `int(sample.off_loop), json.dumps(persisted_finding(finding), separators=(",", ":")),` | `int(sample.off_loop), json.dumps(finding.to_dict(), separators=(",", ":")),` | `test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers` |
| TRX-18 | M1 | `src/probos/admission/report.py` | `"SELECT operation, code, work_kind, off_loop, SUM(findings) FROM ticket_findings WHERE day >= ? "` | `"SELECT operation, code, work_kind, off_loop, SUM(findings) FROM ticket_findings "` | `test_the_ticket_queries_answer_on_a_read_only_connection` |
| TRX-19 | M1 | `src/probos/admission/report.py` | `"FROM ticket_markers GROUP BY boot_id ORDER BY MIN(hour), boot_id"` | `"FROM ticket_markers ORDER BY MIN(hour), boot_id"` | `test_the_ticket_queries_answer_on_a_read_only_connection` |
| TRX-20 | M1 | `src/probos/admission/store.py` | `if _ISSUED_ID.fullmatch(raw):` | `if _ISSUED_ID.match(raw):` | `test_a_persisted_finding_shows_ticket_ids_only_as_digests` |
| TRX-21 | M1 | `src/probos/admission/store.py` | `"DELETE FROM ticket_markers WHERE rowid IN (SELECT rowid FROM ticket_markers ORDER BY hour, boot_id LIMIT ?)"` | `"DELETE FROM ticket_markers WHERE rowid IN (SELECT rowid FROM ticket_markers ORDER BY boot_id, hour LIMIT ?)"` | `test_prune_deletes_old_ticket_days_and_markers_and_leaves_the_rings` |
| TRX-22 | M1 | `src/probos/admission/report.py` | `"GROUP BY operation, code, work_kind, off_loop ORDER BY operation, code, work_kind, off_loop"` | `"GROUP BY operation, code, work_kind ORDER BY operation, code, work_kind, off_loop"` | `test_the_ticket_queries_answer_on_a_read_only_connection` |

How the rows are killed (each TR<n> is the case whose test function the row's Killed-by cell names):
- **TRX-1:** TR1's key list for `ticket_findings` lacks `off_loop`.
- **TRX-2:** TR2's `day` column holds the hour.
- **TRX-3:** TR2's markers' `written` is 0.
- **TRX-4:** TR3's `ticket_missing_samples` stays empty.
- **TRX-5:** TR2's `ticket_findings` is empty.
- **TRX-6, TRX-7:** TR3's ring keeps more rows than its size.
- **TRX-8:** TR2's `ticket_markers` is empty.
- **TRX-9:** TR5 keeps the 2026-09-23 finding day.
- **TRX-10:** TR5 keeps the 2026-09-23T12 marker hour.
- **TRX-11:** TR5 keeps three marker rows under a limit of 2.
- **TRX-12, TRX-13:** TR9's field is the raw id.
- **TRX-14:** TR9's cause keeps the raw ids.
- **TRX-15:** TR9's 16-character hex id is replaced in its cause.
- **TRX-16:** TR9's digest is the raw id.
- **TRX-17:** TR2's ring row contains the raw id.
- **TRX-18:** TR8's query gets one parameter for no placeholder and raises.
- **TRX-19:** TR8's markers come back as one row for the two boots.
- **TRX-20:** TR9's 33-character hex id is replaced in its cause.
- **TRX-21:** TR5 deletes `boot-0`'s marker of the current hour and keeps `boot-a`'s older one.
- **TRX-22:** TR8's `tool`, `ticket_live`, `agentic_run` findings come back as one row for both `off_loop` values.
- **Pinned with no row** (the census does not run them; the orchestrator runs them by execution):
  - lines that hold `|` or are not unique: TR5's `boot-0` marker, which has only an offered count, and TR8's second boot kill the `ticket_hours` union without its `offered`, `dropped` or `samples_dropped` term (its line holds `|`, which this table would have to escape); TR8's limit-1 reads kill each ring query's order without `DESC` (`"ORDER BY seq DESC LIMIT ?"` occurs three times in `report.py`).
  - TRX-15's line: a class wider by one character (`[0-9a-z]{32}`, `[0-9a-fA-F]{32}`, `[\da-f]{32}`, `\w{32}`, `.{32}`) or `re.IGNORECASE`, killed by TR9's ids of 32 characters one of which is not lowercase hex; a narrower class (`[0-9a-e]{32}`, `[a-f]{32}`), killed by its issued ids, which hold every hex digit; other bounds (`{31,32}`, `{32,33}`, `{32,64}`, `{32,}`, `{1,32}`), killed by its ids of 31 and 33 characters and of 16.
  - TRX-20's line: `search` for `fullmatch`, killed by the 33-character id; testing one id's form for both ids (`fullmatch(finding.ticket_id)` or `fullmatch(finding.parent_id)`), killed by TR9's finding with an uppercase id and an issued parent.
  - TRX-14's line: `cause.replace(raw, ticket_digest(raw), 1)`, killed by TR9's cause, which names the ticket's id twice.
  - TRX-16's line: `value.encode("ascii")` or `value.encode("latin-1")`, killed by TR9's digest of a non-ASCII value.
  - TRX-17's line: `json.dumps` without `separators`, killed by TR2's exact ring text.
  - TRX-22's line: the grouping without `operation`, `code` or `work_kind`, killed by TR8's findings that differ in that column alone.
- **Expected to survive** (equivalent, or a property that no TR bullet, name or docstring states):
  - `int(off_loop)` or `int(sample.off_loop)` without `int` (equivalent: `sqlite3` stores a `bool` as 1 or 0);
  - a ring's trim moved out of its `if` (equivalent while the ring sizes do not change between writes: a ring is already within its size);
  - `"hour < ?"` as `"hour <= ?"` in the ticket marker prune, and `count > MARKER_ROW_LIMIT` as `>=` (equivalent: an hour never equals a day string, and the delete's `LIMIT` is then 0);
  - the two retention constants swapped in `prune`'s ticket cutoffs, and `[:16]` for `[:TICKET_DIGEST_CHARS]` (equivalent while the values are equal);
  - `MAX(hour)` for `MIN(hour)` in the markers query's order, and the `boot_id` tie-break of the oldest-marker delete (TR8 states an order by hour, and TR5's oldest hour is unique);
  - `AUTOINCREMENT` or a column's type in the four tables, and the ring queries' columns other than operation, code, work kind and `off_loop` (TR1 states columns, NOT NULL and keys; TR8 reads those four columns).

## 11. Verified Against Codebase (2026-10-30, read on `60440cb2`, tree `2158c8d8`)

```
git rev-parse HEAD HEAD^{tree} 302e6bf9^{tree} -> 60440cb209b8..., 2158c8d806d5..., 75aecaf1d45f...
git log --oneline -6                           -> 60440cb2, 2afc5ff2, 506d2e69, 9f1c9ac4 (M3d3a oracle stages), 9e2096d1 (scratch base: 302e6bf9 plus the M3d3a contract), 302e6bf9 (M3d2 head)
git status --short                             -> (nothing)
git diff --stat 302e6bf9 HEAD                  -> 13 files; none of store.py, report.py, storage_declarations.py, recorder.py or the store, parity and report tests
git ls-files --eol <the edited files>          -> i/lf w/crlf for each (anchor greps use \r?$)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> CEILING: AD-1355 (GitHub issue titles, all states); NEXT: AD-1356

src/probos/admission/store.py
  :3-5 docstring head (M1-01); :24-35 bullets tail, compatibility paragraph, closing quotes (M1-02); :39-50 imports (M1-03)
  :54 STORE_FILENAME; :56 SCHEMA_VERSION = 1; :57 DAY_SECONDS; :60 AGGREGATE_RETENTION_DAYS = 35; :66 AGGREGATE_ROW_LIMIT = 100_000
  :68 SAMPLE_RING_SIZE; :69-70 DISAGREEMENT_RING_SIZE (M1-04); :72 MARKER_RETENTION_DAYS = 35; :74 MARKER_ROW_LIMIT = 50_000
  :79-134 _SCHEMA; :131-134 its last lines (M1-05; `    latency_ns    INTEGER NOT NULL,` occurs once); :144 _TRIM_SAMPLES (the seq-trim shape)
  :167-172 the marker prune comment and _DELETE_OLDEST_MARKERS (M1-06); :175-182 utc_day, utc_hour; :185-190 _rollback_quietly
  :210-228 ShadowDisagreement's tail and ShadowBatch (M1-07); :231-232 class AdmissionShadowStore (M1-08)
  :251-286 start (version check :268, CREATE IF NOT EXISTS via executescript :276); :303 write_batch; :310-313 its docstring tail (M1-09)
  :341-348 hours and markers (M1-10 anchors on :347); :349-365 try, statements, commit, rollback on BaseException (M1-11 anchors on :360-362)
  :368-403 prune; :371-373 its docstring (M1-12); :396-399 marker limit and commit (M1-13)
src/probos/admission/recorder.py:225 prune call; :234-237 ShadowBatch built from seven fields; :241 write_batch call; :250-264 _restore; :266-270 _pending
src/probos/admission/report.py:3-4 docstring (M1-17); :25-54 REPORT_QUERIES, :50-54 its tail (M1-18); :57-68 run_query; :71-73 open_read_only
src/probos/admission/storage_declarations.py:17 title (M1-14); :32-33 retention_note tail (M1-15); :43-48 notes (M1-16)
src/probos/admission/service.py:166-203 hold (issue :183-189, CURRENT_TICKET.set :190); :226-252 _check_ticket (check :238, off_loop count :239-240); :254-256 off_loop_checks
src/probos/admission/tickets.py:60-68 TICKET_EFFECTS, OP_ISSUE, TICKET_OPERATIONS (3), TICKET_FINDING_KEYS; :76 SHOWN_CHARS = 64
  :143-164 TicketFinding (__post_init__ checks operation and code only); :254-286 check; :335 secrets.token_hex(16); :371-373 unknown's shown id
  :379-390 revoked causes; :435-439 _revoked_cause
src/probos/admission/taxonomy.py:27-40 WORK_KINDS (12 values); :85-88 TICKET_REASON_CODES (12 values)
src/probos/agent_stop.py:424 StopRecord(uuid.uuid4().hex, ...): a stop id is 32 lowercase hex characters
src/probos/runtime.py:2928-2939 store and recorder built in start; :2959 the service built with recorder=shadow_recorder
src/probos/startup/shutdown.py:1497-1506 recorder stop, then store stop
scripts/check_architecture_principles.py:187-188 SRP_MAX_BODY_LINES = 500, SRP_MAX_DIRECT_METHODS = 15; :566-568 the checks
scripts/check_store_registry.py:15 rule "Exists -> declared"; :452-531 detect_tables (CREATE TABLE names per module)
scripts/gen_ad_ledger.py:126-132 status keywords; :139 the 120-character head window
tests/fixtures/ad1346_shadow.py:15-16 T0 (2026-10-28T12:00:00Z), HOUR; :37-44 rows
tests/test_ad1346_admission_shadow_store.py:3 S1 bullet (M1-19); :52 TABLES; :105-117 S1 (M1-20); :197-208 S4 (the NULL-boot rollback shape); :211-218 S5 (monkeypatched ring size); :221-233 S6 premises; :288-297 S11
tests/test_ad1346_admission_shadow_parity.py:9 P6 bullet (M1-21); :67 TABLES; :286-303 P6 (M1-22); :451 P13 pins COUNTER_NAMES[-2:] (M3d3b2 must update it)
tests/test_ad1346_admission_shadow_report.py:32-35 Q1 (M1-23); :81-82 read-only delete raises sqlite3.OperationalError; :108-114 Q5
tests/test_ad1346_admission_service.py:99-113 _PERSISTENCE_IMPORTS, store.py at :109-112 (M1-24); :186-193 _module_names; :506-512 T14 docstring, :511-512 (M1-25); :514 the package's file set
tests/test_ad1346_admission_ticket_sinks.py:177-196 stops and registry fixtures (the pattern TR2 follows); :419-420 issue_stop(...).record.stop_id
PROGRESS.md:1 title; :3 M3d3a's paragraph head. DECISIONS.md:1023 M3d3a's heading; :1036 the heading after it (M3-02)
SQLite, "The SQLite Autoincrement" (sqlite.org/autoinc.html, fetched 2026-10-30): "AUTOINCREMENT guarantees that automatically chosen ROWIDs will be increasing but not that they will be sequential."
OWASP ASVS 4 (owasp-aasvs4.readthedocs.io, V7.1, fetched 2026-10-30), 7.1.1: "Credentials or payment details are not logged. Session tokens are logged in a hashed form"
```

## Absence Verified (2026-10-30, run on `60440cb2`, tree `2158c8d8`)

```
CLAIM: no Python file names the identifiers this contract introduces
RUN:   Grep "offer_ticket|ticket_findings|ticket_samples|ticket_missing_samples|ticket_markers|TicketBatch|TicketSample|TICKET_SAMPLE|TICKET_MISSING_RING|ticket_late|ticket_offered|ticket_written", glob *.py, the whole worktree
FOUND: no matches
HOLDS: yes (a Markdown search finds only prompts/ad-1346-m3d3a-ticket-sinks.md, R46's direction)

CLAIM: in src, write_batch and prune of the shadow store are called only by the recorder
RUN:   Grep "write_batch\(|\.prune\(" src/probos
FOUND: recorder.py:225, :241; store.py:303 (def); infrastructure/backup.py:364, runtime.py:4046, :4066 (other objects' prune)
HOLDS: yes

CLAIM: in src, the registry's issue, issue_child and check are called only in service.py
RUN:   Grep "\.issue\(|\.issue_child\(|_tickets\.check\(|offer\(" src/probos
FOUND: service.py:183, :187, :238; recorder.py:119 (def offer), service.py:148 (shadow's offer); the rest are other objects (routers' store.issue, dispatch offers, pre-clearance offers)
HOLDS: yes

CLAIM: only S1 and P6 pin the store's table list, and only Q1 pins REPORT_QUERIES's names
RUN:   Grep "COUNTER_NAMES|REPORT_QUERIES|sqlite_master|ShadowBatch\(|..." tests, glob test_ad1346_admission_*.py
FOUND: sqlite_master in shadow_store.py:52 and shadow_parity.py:67 (S1 at :114-117, P6 at :296 and :300-303); REPORT_QUERIES in shadow_report.py:20, :32, :36, :39
HOLDS: yes

CLAIM: no architecture-baseline row names the store or the recorder, and store-baseline.yaml names no admission entry
RUN:   Grep "ShadowRecorder|AdmissionShadowStore|AdmissionService|admission" docs/development/architecture-baseline.yaml; Grep "admission|AdmissionShadowStore" docs/development/store-baseline.yaml
FOUND: no matches; no matches
HOLDS: yes

CLAIM: no generated document repeats the declaration's text
RUN:   Grep "admission\.shadow-decisions|admission_shadow\.db" outside prompts/, files
FOUND: PROGRESS.md, DECISIONS.md, admission/taxonomy.py, admission/storage_declarations.py, admission/store.py, admission/report.py, and eight tests
HOLDS: yes (no docs/ file)

CLAIM: no test reads the store's, the report's or the declaration's text other than Q5's constants check and T14's imports
RUN:   Grep "store\.py|report\.py|storage_declarations|__doc__" tests, glob test_ad1346_*.py
FOUND: service.py:104, :108, :109 (T14's allowlist keys); shadow_parity.py:68 (a comment); shadow_report.py:110 (Q5); shadow_store.py:290 (S11's module name)
HOLDS: yes

CLAIM: a Captain's stop id has the form of an issued ticket id, so the cause rule must not digest every 32-hex run
RUN:   Grep "stop_id\s*=|token_hex|uuid" src/probos/agent_stop.py
FOUND: :31 import uuid; :424 StopRecord(uuid.uuid4().hex, ...)
HOLDS: yes (D144 keys on the finding's own ids)

CLAIM: store-registry tests do not pin the admission module's tables
RUN:   Grep "admission|detect_tables|tables\[" tests/test_ad1256_store_registry.py
FOUND: detect_tables unit cases on inline sources only (:634-742)
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** no baseline row changes, and `architecture-baseline.yaml` stays byte-identical.
  - `AdmissionShadowStore` keeps 8 direct methods.
  - Its span grows from 173 to 218 lines by `ast`, below 500 (the orchestrator's pre-build run, 2026-10-30).
  - The new functions are module-level. No `create_task` and no `connect` is added in `src`.
- **`check_store_registry.py --check`:** passed in the orchestrator's pre-build run (2026-10-30) with `store-baseline.yaml` unchanged and the base's numbers (`declarations=26, store modules=73, undeclared=47, baselined=47`). The four tables sit in the declaration's owner module, as M3c1's two did. M1's gate runs it.
- **`check_seam_contracts.py`:** not touched; no seam symbol changes.
- **Config:** no field.
- **T14:** `store.py`'s allowlist gains `hashlib`, `re` and `probos.admission.tickets` (M1-24). The other allowlists, the logging rule and `__all__` are unchanged.
- **Every sentence and test that quotes a set this slice changes:**
  - `store.py`'s module docstring (M1-01, M1-02), `ShadowBatch`'s, `write_batch`'s and `prune`'s docstrings (M1-07, M1-09, M1-12);
  - the declaration's title and notes (M1-14 to M1-16);
  - `report.py`'s docstring (M1-17);
  - S1 and its bullet, P6 and its bullet, Q1, T14 and its docstring (M1-19 to M1-25), and in the new file TR1's and TR7's table lists and TR7's `ticket_` names; Q2's bullet and name are the exception §14 item 7 names.

  `taxonomy.py`'s docstring (the db persists the verdict's values, and the ticket codes keep the same rule) and `carrier.py`'s ("Nothing here ... is persisted", said of the carrier) stay true. M3d3a's dated entries, which say the sink record is M3d3b's, are records of their date.
- **`gen_ad_ledger.py --check`:** passes after M3 regenerates both files (prediction).
- **Test collection:** `git diff --name-status --diff-filter=AD <slice base>..HEAD -- 'tests/test_*.py'` lists exactly one `A` file, `tests/test_ad1346_admission_ticket_record.py`.
- **D143's older-build check** (run by the orchestrator before the build, 2026-10-30; Process says when it is run again on the M1 stage).
  - Save this script outside the repository, in a directory of its own.
  - `<old>` is a checkout of the build base (`git worktree add <old> <base commit>`; `<base commit>` is `origin/main` at the M3d3a merge).
  - `<new>` is the M1 stage's worktree.
  - `<A>` and `<B>` are two empty scratch directories.

  ```python
  """AD-1346 M3d3b1, D143's older-build check: python -P <this file> <src dir> <data dir> <write | old | new>."""
  import asyncio
  import sys
  from pathlib import Path

  SRC, DATA, PHASE = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
  sys.path.insert(0, str(SRC))

  import probos  # noqa: E402

  assert Path(probos.__file__).resolve().is_relative_to(SRC), probos.__file__
  from probos.admission import report, store  # noqa: E402

  T0 = 1_793_188_800.0  # 2026-10-28T12:00:00Z, the T0 of tests/fixtures/ad1346_shadow.py
  HOUR, OLD_HOUR = store.utc_hour(T0), store.utc_hour(T0 - 40 * store.DAY_SECONDS)
  LIMITED = {"would_refuse_samples", "disagreement_samples", "ticket_samples", "ticket_missing_samples"}
  COUNTS = (
      "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
      "(SELECT COUNT(*) FROM ticket_missing_samples), (SELECT COUNT(*) FROM ticket_markers)"
  )


  def verdicts(*hours):
      return {(hour, "intent", "intent", "admit", "admitted", 3): 1 for hour in hours}


  async def main():
      shadow = store.AdmissionShadowStore(data_dir=DATA)
      await shadow.start()
      try:
          if PHASE == "write":
              from probos.admission.tickets import TicketFinding

              raw = "0123456789abcdef" * 2
              revoked = TicketFinding(
                  "tool", "ticket_revoked", f"Ticket {raw} is revoked: its principal or an ancestor's is under the Captain's stop s.",
                  ticket_id=raw, principal_key="agent", work_kind="agentic_run", stop_id="s",
              )
              missing = TicketFinding("model_call", "ticket_missing", "No ticket was presented at model_call.")
              tickets = store.TicketBatch(
                  findings={
                      (HOUR, "tool", "ticket_revoked", "agentic_run", False): 2,
                      (OLD_HOUR, "model_call", "ticket_missing", "", True): 3,
                  },
                  samples=[store.TicketSample(HOUR, T0, revoked, False)],
                  missing=[store.TicketSample(OLD_HOUR, T0, missing, True)],
                  offered={HOUR: 2, OLD_HOUR: 3},
              )
              batch = store.ShadowBatch(verdicts(HOUR, OLD_HOUR), [], {HOUR: 1, OLD_HOUR: 1}, {}, {}, tickets=tickets)
              print(PHASE, "written", await shadow.write_batch("boot-write", batch))
          else:
              batch = store.ShadowBatch(verdicts(HOUR), [], {HOUR: 1}, {}, {})
              print(PHASE, "written", await shadow.write_batch(f"boot-{PHASE}", batch))
              print(PHASE, "prune", await shadow.prune(T0))
      finally:
          await shadow.stop()
      db = await report.open_read_only(DATA / store.STORE_FILENAME)
      try:
          for name, sql in report.REPORT_QUERIES.items():
              params = (10,) if name in LIMITED else ("2026-09-01",) if "?" in sql else ()
              print(PHASE, name, await report.run_query(db, name, params))
          async with db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name LIKE 'ticket%'") as cursor:
              (tables,) = await cursor.fetchone()
          if tables:
              async with db.execute(COUNTS) as cursor:
                  print(PHASE, "ticket rows", tuple(await cursor.fetchone()))
          else:
              print(PHASE, "ticket tables", tables)
          async with db.execute("PRAGMA integrity_check") as cursor:
              print(PHASE, "integrity", tuple(await cursor.fetchone()))
      finally:
          await db.close()


  asyncio.run(main())
  ```

  Run, each command alone, with `d:/ProbOS/.venv/Scripts/python.exe -P <script>`:
  1. `<new>/src <A> write`
  2. `<old>/src <A> old`
  3. `<new>/src <A> new`
  4. `<old>/src <B> old`
  5. `<new>/src <B> new`

  Then `git worktree remove <old>`.

  Expected lines (the orchestrator's pre-build run of 2026-10-30 printed each as listed; Process says when it is run again):
  1. `write written 2`, `write ticket rows (2, 1, 1, 2)`, `write integrity ('ok',)`.
  2. `old written 1`, `old prune (1, 1)`, `old ticket rows (2, 1, 1, 2)` (the older build leaves the four tables alone), `old integrity ('ok',)`, and no `ticket_` query line.
  3. `new written 1`, `new prune (0, 0)`, `new ticket rows (1, 1, 1, 1)` (the 2026-09-18 finding and marker are pruned, and the rings stay), `new ticket_findings_by_operation [('tool', 'ticket_revoked', 'agentic_run', 0, 2)]`, `new integrity ('ok',)`.
  4. `old prune (0, 0)`, `old ticket tables 0`.
  5. `new ticket rows (0, 0, 0, 0)`, `new days_recorded [('2026-10-28',)]` (the older build's rows kept), `new integrity ('ok',)`.

  Any exception, or a different line, is a hard stop for the Architect. Record the printed output in the DECISIONS bullet (§8).

## 13. Prior Art and Blind Spots

**Internal (adopted):**
- M3b's D9 and D10 (a dedicated bounded store, rings and per-boot-hour markers) and its `write_batch` and `prune` shapes. The new tables copy them.
- M3c1's D58 (additive tables under version 1, with the older-build check executed: `prompts/ad-1346-m3c1-shadow-seams-sinks.md:2816`). D143 repeats it.
- AD-1213's rollback-before-later-commit (`_rollback_quietly`). It is reused unchanged.
- F-209 (a bound from day one). D139 sets one.
- M3d3a's D128 (`off_loop`) and register R46 (the direction this contract refines in D137 and D138).

**External:**
- **SQLite AUTOINCREMENT** (§11): ids increase but may have gaps. Adopted: the rings are described as keeping "at most" their size (register R56).
- **OWASP ASVS 4, requirement 7.1.1** (§11): session tokens are logged in hashed form. Adopted for D144, where the ticket id is the in-process bearer reference; a truncated SHA-256 keeps correlation within the file.
- Third-party summaries of the OWASP Logging Cheat Sheet and AWS logging guidance say the same (hash or mask session ids and tokens). They are not quoted, because the cheat sheet's own wording was not fetched.
- `docs/research/reference-projects.md`, judged on 2026-10-30: no row bears on a persisted shadow record's schema or retention. None was searched (considered, deferred), and no row update is proposed.

**Blind spots** (register items in brackets):
1. `ticket_missing` volume could flood one shared ring (D138: a ring of its own) [R57].
2. Persisted bearer ids (D144).
3. A stop id has the issued-id form (D144's own-ids rule).
4. An older build after this one leaves work-ticket rows unpruned [R54].
5. The `ticket_` queries on a file without the tables [R55].
6. Ring gaps and rings outliving the window [R56].
7. The store does not check the work kind, so the bound depends on the writer [R53].
8. The record is built and tested with no producer in `src` until M3d3b2, by design [R52].
9. A crash loses the findings pending since the last flush with no marker for them (up to `FLUSH_INTERVAL_SECONDS`, as for verdicts) [R52 carries it to M3d3b2's markers report].

## 14. Diff Reviewer: properties to verify

1. **Compatibility.**
   - The five existing tables' DDL, keys and statements are byte-identical.
   - `SCHEMA_VERSION` is 1, and `start`'s version check is unchanged.
   - Each new table is `CREATE TABLE IF NOT EXISTS` inside `_SCHEMA`.
2. **One transaction.**
   - Every work-ticket statement runs inside `write_batch`'s existing `try`, before its one `commit`.
   - A raise in any of them reaches the existing `except BaseException`, whose `ROLLBACK` (`_rollback_quietly`) also undoes the verdict statements that ran before it in the transaction. This is read, not tested: TR4's failing batch has no verdict part.
   - A raise while the rows are built, before the `try`, comes before every statement, so nothing of the batch is written, its verdict part included.
   - The rows are built before the `try`, as the existing samples' JSON is.
3. **Bounds.**
   - Each ring is trimmed after its own insert by `seq`.
   - `prune` deletes `ticket_findings` days with the aggregate cutoff expression and `ticket_markers` with the marker expressions, then the oldest beyond `MARKER_ROW_LIMIT`, after the existing statements and in the same transaction.
   - `prune`'s and `write_batch`'s return values are unchanged.
4. **What is kept.**
   - A ring row's JSON is `persisted_finding`: its `ticket_id` and `parent_id` are digests, and the cause shows neither of the finding's own ticket and parent ids where that id has the issued form. Any other text in the cause, a stop id included, is kept.
   - `stop_id`, `principal_key` and `presented_key` are kept; the verdict samples already persist `key`, `presented_id` and `stop_id`.
5. **No producer.**
   - `recorder.py`, `service.py` and `runtime.py` are untouched.
   - Nothing in `src` fills a `TicketBatch` (§15's grep).
6. **Report.** Names are appended and none is changed; each new SQL is one SELECT; Q5 holds.
7. **Head text.** Each docstring and comment in `store.py`, `report.py`, `storage_declarations.py`, the edited tests and the new file is true at its own milestone, except Q2's module bullet and name in `tests/test_ad1346_admission_shadow_report.py`. They say each and every query, but since M3c appended two queries Q2 has run only M3b's six; this slice appends five more, which TR7 and TR8 run (P12 runs M3c's two). No line number of a file this slice edits appears in head text.
8. **Test file hygiene.**
   - The new file's text reads no environment variable, imports or calls no `subprocess` or `socket`, starts no thread and no runtime, and puts every data directory under `tmp_path` (§15).
   - These are properties of the file's text.

## 15. Acceptance criteria

- The updated files and the new file pass, and each §10 mutant is killed.
- `grep -nE "LOCALAPPDATA|AppData|environ|getenv|(import|from) (subprocess|socket)|(subprocess|socket)\.|create_subprocess|Popen|Thread|ProbOSRuntime" tests/test_ad1346_admission_ticket_record.py` finds nothing.
- `grep -n "data_dir=" tests/test_ad1346_admission_ticket_record.py` prints five lines, each containing `tmp_path /`: the `store` fixture's, the `stops` fixture's, TR7's two and TR8's.
- `grep -rn "TicketBatch(" src/probos` prints nothing (nothing in `src` fills a work-ticket part).
- `grep -rlE "ticket_findings|ticket_markers|ticket_missing_samples" src/probos` prints `src/probos/admission/store.py`, `src/probos/admission/report.py` and `src/probos/admission/storage_declarations.py` only.
- `git diff --stat <slice base>..HEAD -- src/probos/admission/recorder.py src/probos/admission/service.py src/probos/runtime.py` prints nothing.
- The §12 `--check` scripts pass, D143's check prints its expected lines, and the broad gate's receipt is green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Corrections to this contract

A1 (2026-10-30, after the orchestrator's pre-build run on `41324376`, the M3d3a candidate head, and its dry application on `60440cb2` and `41324376`) repairs:
- Defect 1: predictions since measured. The dry application (A1-1), the collected count (A1-5), D143's executed check (A1-3, A1-11, A1-33, A1-34), the census, now of record under a stated condition (A1-4), the span and the store registry check in D145 and §12 (A1-12, A1-31, A1-32), and §17, which now lists only what is not yet confirmed (A1-39). §12's ledger line and D146's figures stay predictions.
- Defect 2: the base statement now says M3d3a is built, in review and not merged (A1-2). The records of `60440cb2` stay dated to it, the `git diff --stat 302e6bf9 60440cb2` record included.
- Defect 3, the sweep:
  - claims wider than the code or the tests: D138's model and tool calls (A1-7); the store's "each bounded" (A1-14); `ticket_findings`'s bound and `off_loop` meaning, which the store neither checks nor gives (A1-15, A1-26); the ring-size comments, which named codes the store does not read (A1-16); `TicketSample`'s docstring, which gave an issue finding a sink check (A1-17); the report docstring's account of which files lack the tables, and its "parity queries" for two names (A1-18); TR2's bullet (A1-19); PROGRESS's ring content and prune constants (A1-20, A1-21); DECISIONS' D138, which stated M3d3b2's sampling rules as this slice's, and D140's loop (A1-25, A1-27); §9's existing constants, of which `_SCHEMA` changes (A1-30); §14 item 4's cause rule (A1-37).
  - absence and exclusivity claims that the new test file or the declaration falsifies: "nothing fills", now scoped to `src` and a vessel (A1-6, A1-22, A1-24); §5's "no other `src` file", which the declaration's notes falsify (A1-13); "neither reads nor writes", where the declaration's backup is "included", now "no statement names" (A1-10, A1-23, A1-28, A1-29).
  - a wrong edge sentence: D139 said a raising `utc_day` raises at the first existing statement, but `prune` computes `utc_day(now)` before its `try` (A1-8).
  - a rollback sentence that covered part of the case: §14 item 2 now says what the rollback undoes, that no test fails a batch with a verdict part, and that a raise while the rows are built writes nothing of the batch (A1-36). Register R52 gains the consequence for M3d3b2, whose `_restore` would add a failing part back (A1-40).
  - presupposed producers: D139's restart sentence (A1-9) and blind spot 8 (A1-35).

Landing text changes in §7.1 (M1-01: A1-14; M1-02: A1-15; M1-04: A1-16; M1-07: A1-17), §7.3 (M1-17: A1-18), §7.10.N (the module docstring's TR2 bullet: A1-19) and §8 (M3-01: A1-20 to A1-23; M3-02: A1-24 to A1-29). No SEARCH text of §7 or §8, statement, `def`, test assertion, case count or mutation row changes, and the slice still has 27 pairs. No decision or register row is added; R52 gains a bullet.

A2 (2026-10-30, after the M3d3a review's findings F1 to F4: their four classes swept on this contract before its build, on `21b507d7`, M3d3a's candidate `1ae78c8a` plus this contract) repairs:
- Claims about who builds, uses or reads a name (the class of F1 and F2): §5's `ShadowBatch` builders (Q2 passes the first five fields by keyword), the users of the new names (D143's check), the four tables' consumers (`start`, D143's check, TR7's drop, `check_store_registry.py` and the backup), the `REPORT_QUERIES` consumers (Q1's `SELECT` check, Q5, TR7, TR8 and D143's check) and the declaration's readers (`check_store_registry.py` requires the title not to be blank) (A2-3); the new file's intro, which said every test writes the work-ticket part (A2-5); M3-02's D138, "reads no sample's code", although each ring row's `code` column is the finding's (A2-18); §12's "no `connect` is added", which TR7 falsifies, now scoped to `src` (A2-24); §12's list of the text that quotes a changed set, which left out TR1 and TR7 (A2-25); and §14 item 7, which Q2's bullet and name falsify (A2-26, below).
- F3's class: the front matter called each SEARCH text's uniqueness a whole-line match, but M3-01's last SEARCH line is a prefix of its line. The parenthetical is deleted (A2-1); no other SEARCH text of §7 or §8 ends in part of a line.
- Coverage claims wider than an assertion (F4's class): TR3's bullet, of which only a write to the missing ring alone is tested (A2-6); TR4's bullet and docstring, which named the failing statement and its order after the finding upsert, which no assertion fixes (A2-7, A2-11); T14's docstring, "for a type only", which T14 does not check (A2-4); and §10's TRX-1 note, whose "every write raises" holds only for a write with a finding count (A2-21).
- The rulings (Architect, 2026-10-30), each option S: TR5 said `prune` leaves the rings with its `ticket_samples` ring empty, and now writes an old row to each ring and counts both (A2-12, A2-13); TR8 left alive the `ticket_missing_samples` order, the markers query without `GROUP BY` and the marker hours without their dropped terms, and now writes a second missing sample and a second boot whose only counts are a dropped and a samples-dropped count at hours of their own (A2-8, A2-14 to A2-16), with §10's new row TRX-19 (A2-20, A2-23); TR9 left alive a regex for any lowercase-hex length or for either case, and now checks a 16-character hex id and a 32-character uppercase one (A2-9, A2-17), with TRX-15's mutant now `[0-9a-f]+` (A2-19, A2-22); and "compact JSON" was checked by no assertion, so TR2 now compares the ring's text (A2-10), which keeps `src` unchanged.
- A summary a repair made wrong (R2-1's class): the front matter's account of M3d3a's candidate, which its A2 repair moved to `1ae78c8a` (A2-2), and §17's item 4, which the orchestrator's run on the A1 text confirmed (A2-28).
- Not repaired: Q2's module bullet and name in the edited report test say each and every query, but Q2 has run only M3b's six since M3c. Repairing them needs a new pair in §7.6, which an amendment pair cannot carry; the queries Q2 does not run are run by P12, TR7 and TR8, and §14 item 7 names the exception (A2-26).

Landing text changes in §7.7 (M1-25: A2-4), §7.10.N (A2-5 to A2-17) and §8 (M3-02: A2-18); §7.1 to §7.6 do not change. A2's executable changes are statements and assertions of TR2, TR5, TR8 and TR9 (A2-10, A2-12 to A2-17); no `def`, no SEARCH text of §7 or §8 and no line of `src` changes, and the slice still has 27 pairs and 9 cases. §10 now has 19 rows: TRX-19 is new and TRX-15's Mutate-to changed. No decision or register row is added; D149 and R58 stay free.

A3 (2026-10-30, after cross-family review round 1 on `4d6ce6f5`, the M3d3b1 candidate: four findings, each a false sentence, and no production defect) repairs:
- F1, TR9's bullet: it said an id of another alphabet, length or case stays in the cause, and `_ISSUED_ID` as `[0-9a-z]{32}` or `[0-9a-f]{32,64}` passed TR9. Ruled S (Architect, 2026-10-30). TR9's issued ids now hold every hex digit, and its cause names the ticket's id twice (A3-11). Its ids not of the issued form are 16, 31 and 33 lowercase hex characters, and 32 characters one of which is any other printable ASCII character or an Arabic-Indic digit. One finding has an uppercase id and an issued parent. `ticket_digest` is checked on a non-ASCII value, because D144 and its docstring say "over UTF-8" (A3-12). The bullet states what these pin (A3-2). New row TRX-20 (A3-17, A3-19).
- F1's class, coverage claims, swept clause by clause over TR1 to TR9 against each token's one-line mutants:
  - TR5's "the oldest markers" was tested with one boot, so a delete ordered by boot first passed. TR5 now adds a second boot's newer marker and a limit of 2 (A3-3, A3-4). This also kills the `ticket_hours` union without its `offered` term. New row TRX-21; TRX-11's note follows (A3-17 to A3-19).
  - `ticket_findings_by_operation` passed without any one of its four grouping columns. TR8's findings now differ in each column alone, and its bullet says so (A3-1, A3-7 to A3-10). New row TRX-22.
  - §10 lists the mutants left alive, each equivalent or claimed by no clause (A3-20).
- F2, Q5: Q5 rejects constants that begin with a write or schema keyword; it is not a prefix allowlist. D145's and §12's prefix sentences are deleted (A3-15, A3-21). §1's account of Q5 and §14 item 6 are kept.
- F3: "no build writes a row into them before M3d3b2" is deleted from M3-02's *Reversal.* bullet (A3-13).
- F4: §5's sentences on the retention note and on no other text field are deleted. `check_store_registry.py` extracts every keyword of the call and reads `retention_note` before testing the retention (A3-16).
- F2 and F4's class, what a test reads or checks: S11 does not pin the declaration's lifecycle owner. §5's "S11 pins the other fields" is deleted (A3-16), and §1's record now names the exception (A3-14).
- F3's class, what a build does: TR7's docstring and premise message said the tables "a build without them" creates, which an M3b build's three tables are not. Both now name AD-1346 M3c's store (A3-5, A3-6). TR8's docstring said `boot-0`'s hours sort after `boot-a`'s, but one of them is also one of `boot-a`'s. It now says the first hour does (A3-7).

Landing text changes in §7.10.N (A3-1 to A3-12, `tests/test_ad1346_admission_ticket_record.py`) and §8 (M3-02: A3-13, `DECISIONS.md`); §7.1 to §7.7 do not change, and no line of `src` changes. A3's executable changes are statements and assertions of TR5, TR8 and TR9 (A3-4, A3-8 to A3-12); no `def` and no SEARCH text of §7 or §8 changes, and the slice still has 27 pairs and 9 cases. §10 now has 22 rows: TRX-20, TRX-21 and TRX-22 are new. No decision or register row is added.

## 17. Claims not yet confirmed

1. `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` after M3 regenerates the ledger on the real tree. The oracle's tracker stage did not regenerate it, and the ledger test failed 3 there, as expected.
2. On the merged M3d3a base: the pairs M1-24, M1-25, M3-01 and M3-02, and the M3d3a code cited under "Which text describes the head".
3. Whether the orchestrator's D143 run stays of record (the two `git diff --stat` conditions of its Process bullet; A2 and A3 change no file under `src`). The census does not: A3 changes the new file, so under Process the campaign of record reruns the unmutated baseline and all 22 rows.
4. The A3 text, which no gate has run: the statements and assertions it adds to TR5, TR8 and TR9 (A3-4, A3-8 to A3-12) and the kills of TRX-20, TRX-21 and TRX-22. The A2 text was built as M2 (`3e39d0b9`): on `4d6ce6f5` the new file and the four edited test files passed (70, the orchestrator's run), and cross-family review round 1 ran rows TRX-1, TRX-2, TRX-6, TRX-9, TRX-15, TRX-17, TRX-18 and TRX-19 there, each killed.

The orchestrator's run on the A1 text (2026-10-30, scratch trees of `41324376`) confirmed what item 4 listed before A2: an AST comparison of the eight code files, docstrings stripped, found no executable line changed; the census killed 18 of 18 rows after an unmutated baseline of 9 passed; D143's five commands exited 0 and printed every expected line; M1's focused list passed (473); and the new file collected 9.

## For the register (#1604)

- **Advanced by this slice:**
  - property 8's durable record and its marker table (no producer yet);
  - the persisted evidence tables for properties 3 and 5 and for registers R37, R38, R39 and R49.
- **R46:** refined and split by D137. M3d3b1 delivers the tables, writes, bounds, report queries, declaration and the executed older-build check; the rest is R52.
- **R52 (M3d3b2: the writer and the offers; binding direction, which its contract re-verifies and may refine; depends on M3d3b1 merged):**
  - `ShadowRecorder.offer_ticket(finding, *, off_loop)` as D140 states, with its pending `TicketBatch` detached in `_flush`, added back in `_restore` within the buffers, and counted in `_pending`.
  - `COUNTER_NAMES` appends `ticket_offered`, `ticket_written`, `ticket_dropped`, `ticket_samples_dropped`, `ticket_late` (update P13's `COUNTER_NAMES[-2:]`).
  - `stop`'s warning names the findings not written. T14's `recorder.py` allowlist gains `probos.admission.tickets`.
  - Offers in `_check_ticket` (after the `off_loop` count) and in `hold` (before `CURRENT_TICKET.set`); the docstrings of `service.py`'s module, `hold` and `_check_ticket` follow.
  - A chain test: the real run entry's sinks, a Captain's stop, `recorder.stop()`, then `ticket_findings_by_operation` shows `ticket_revoked` at both effects and `ticket_markers_by_boot` shows offered equal to written.
  - A boot test whose model call is persisted after `runtime.stop()`.
  - D146's cost measurement; D147 applies from its deploy.
  - Also count the crash window in the property 8 report (blind spot 9).
  - A work-ticket part that raises fails the whole `write_batch`, its verdict part included (one transaction, D140), and `_restore`, as the first bullet directs, would add it back for the next flush. State how a part that raises on every write is bounded, so that it does not hold back the verdict record (for example `offer_ticket`'s checks, or not restoring a part whose write raised).
- **R53:** `ticket_findings`'s per-day bound assumes work kinds in `WORK_KINDS` or empty. The store and `TicketFinding` do not check it, and M3d3b2's `offer_ticket` must. A wall clock that steps back can leave more days than 35 (as for parity).
- **R54:** while a build without the four tables runs, it neither prunes nor writes them. Their rows wait, bounded by what was written before, for a build with the tables.
- **R55:** the `ticket_` report queries raise `sqlite3.OperationalError` on a file without the tables (TR7). The M4 ruling's queries must run on a file the vessel's current build has started.
- **R56:** the rings are trimmed by count, not pruned by day. With few findings a sample can outlive the 35-day window, and after gaps in `seq` a ring can keep fewer rows than its size.
- **R57:** the `ticket_missing` ring keeps the newest 1,000 at most. It shows recent principals with no ticket, not every one over the period; M3e's census reads the counts with it.
- **Inherited and still open:** registers R10, R13 to R18, R19 to R23, R24 to R28, R32 to R34, R36, R37 to R45, R47 to R51.
