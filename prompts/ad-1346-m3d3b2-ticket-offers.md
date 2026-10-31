# AD-1346 M3d3b2 (#1604): the recorder's offers, the work-ticket findings of an issue and a sink check written to `admission_shadow.db`

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-30
**Status:** build-ready. **Issue:** #1604 (AD-1346 M3, epic #1601). The second and last M3d3b slice: M3d3b1's register R52, refined by D149 to D159. No new AD or BF number: M3 takes AD-1346 (`scripts/ad_ceiling.py` on 2026-10-30: ceiling AD-1355 from GitHub issue titles, next AD-1356; none allocated here). **Tier:** HIGH (M1, M2), docs (M3). Nothing parked.
**Dependencies:** AD-1346 M3d3a (`prompts/ad-1346-m3d3a-ticket-sinks.md`) and M3d3b1 (`prompts/ad-1346-m3d3b1-ticket-record-store.md`) merged to `origin/main`. The build base is `origin/main` at the M3d3b1 merge.
**Anchors:** every SEARCH text in §7 and §8 was read on the detached checkout `35045636` (tree `b6343ecb`): M3d3a's candidate `1ae78c8a` (tree `a7fd7db1`) plus M3d3b1's contract and its milestones applied by tool (the M3d3b1 oracle; scratch commits, never pushed). 21 pairs (M1 18, M2 1, M3 2), 1 new file besides this contract (`tests/test_ad1346_admission_ticket_offers.py`), 2 regenerated files in M3 (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`). Dry-applied by the orchestrator before A1 (2026-10-30) on scratch trees of `4d6ce6f5` plus this contract: the 21 pairs and the new file with 0 failures (its M1, M2 and tracking stages; 8 files, +858 -23).
**Contract file:** `prompts/ad-1346-m3d3b2-ticket-offers.md`.

**Identifiers.**
- Register rows: M3c1's R10 to R18, M3c2's R19 to R23, M3c3's R24 to R28, M3d1's R29 to R36, M3d2's R37 to R45, M3d3a's R46 to R51, M3d3b1's R52 to R57 and this contract's R58 to R64 are written "register R<n>".
- Tests: recorder tests R<n> (`tests/test_ad1346_admission_shadow_recorder.py`), parity tests P<n>, service tests T<n>, M3d3a's SK1 to SK10, M3d3b1's TR1 to TR9, and this slice's TO1 to TO12 (`tests/test_ad1346_admission_ticket_offers.py`).
- Mutation rows here are OX-<n>.
- Decisions D149 to D159 are numbered after M3d3b1's D137 to D148. #1604's properties are numbered 1 to 13.

**Which text describes the head.**
- **Records of the read tree `b6343ecb` (commit `35045636`):** the Status and Anchors paragraphs, §1, §11 (Verified Against Codebase, Absence Verified), the internal citations in §13, each citation elsewhere marked "on `35045636`", and every SEARCH text in §7 and §8. Each SEARCH text occurs once in its file on that tree, and no earlier pair of this contract edits those lines. M3-01's last SEARCH line is a prefix of its line; no other SEARCH text ends in part of a line.
- **M3d3b1 is built and not merged** (2026-10-30). `git diff --stat 35045636 4d6ce6f5 -- src tests` prints nothing, so every SEARCH text read on `35045636` holds on `4d6ce6f5` (tree `0656f348ea5a`), the M3d3b1 candidate A1 read; a repair may move the M3d3b1 text listed below. `git diff --stat 1ae78c8a 35045636` lists neither `recorder.py` nor `service.py`, so M1-01 to M1-15 depend on M3d3a's merged text only. The build base is `origin/main` at the M3d3b1 merge. On that base, before the build, re-verify:
  - the M3d3b1 files this contract **edits**:
    - `tests/test_ad1346_admission_service.py`. M1-18 anchors on the T14 docstring sentence M3d3b1 wrote. M1-17's `recorder.py` allowlist lines are not touched by M3d3b1.
    - `tests/test_ad1346_admission_shadow_parity.py`. M1-16's P13 lines are not touched by M3d3b1; M3d3b1 edits P6 and its bullet in the same file.
    - `tests/test_ad1346_admission_ticket_record.py`. M2-01 anchors on M3d3b1's module docstring.
    - `PROGRESS.md` (M3-01 anchors on M3d3b1's paragraph head) and `DECISIONS.md` (M3-02 anchors on the heading that follows M3d3b1's entry).
  - the M3d3b1 code it **cites**, unedited:
    - in `store.py`: `TicketSample`, `TicketBatch` (field order findings, samples, missing, offered, dropped, samples_dropped), `ShadowBatch.tickets`, `ticket_digest`, `persisted_finding`, `TICKET_SAMPLE_RING_SIZE`, `TICKET_MISSING_RING_SIZE`, and `write_batch`'s ticket rows (built before its `try`, written inside it);
    - in `report.py`: the five `ticket_` queries.

  If the merged text of any of these differs, re-verify the pair or the citation against it.
- **Parts that describe the candidate's head and name no commit:** the Milestones and Tests lists, §2 to §6, §8's tracker text, §9, §10, §12, §14 and §15.
- **Text inside the new-file block** (docstrings, comments) is head text and is reviewed as such.
- Where a record and the candidate differ, re-measure; the record does not bind.

**Milestones:**
- **M1 (HIGH):** the recorder and the service. `ShadowRecorder` gains `offer_ticket`, its pending work-ticket part, D150's second write, `_restore`'s work-ticket part, the start mark, the five counters and the stop warning's counts. `AdmissionService.hold` and `_check_ticket` offer their findings, and the docstrings that describe them follow. P13 and T14 are updated.
- **M2 (HIGH):** new `tests/test_ad1346_admission_ticket_offers.py` (TO1 to TO12), and the record test's module docstring.
- **M3 (docs):** `PROGRESS.md`, `DECISIONS.md`, and the AD ledger regenerated by its tool.

**Process:**
- Each milestone is one Builder delegation and one local commit. Stage by explicit path, never `git add -A`. `git add` the new file before M2's focused gate.
- Commit subjects take the form `AD-1346 M3d3b2, M<n>: ... (#1604)`.
- D156's cost run is made by the orchestrator on the M1 stage, before the review.
- One cross-family review (`gpt-6.1-sol`) of M1 and M2 against §14.
- One mutation campaign of record on the M2 tree (§10), after an unmutated baseline passes.
- The broad gate runs once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1346-m3d3b2 --receipt logs/gates/ad1346-m3d3b2.receipt.json`.

**Tests:**
- New: `tests/test_ad1346_admission_ticket_offers.py` (M2), TO1 to TO12. The block in §7.5.N defines 12 `def test_` functions and no parametrised case; the pre-build run collected 12, and A1 adds no case.
- Updated (M1), each file's `def test_` count unchanged:
  - `tests/test_ad1346_admission_shadow_parity.py`: P13's `COUNTER_NAMES` pin, now by position;
  - `tests/test_ad1346_admission_service.py`: T14's `recorder.py` allowlist and its docstring.
- Updated (M2), docstring only: `tests/test_ad1346_admission_ticket_record.py`'s module docstring.
- The acceptance greps for the new test file are in §15.

## 1. Problem

- M3d3b1 built the four `ticket_` tables, and nothing in `src` fills them:
  - `ShadowRecorder._flush` builds each `ShadowBatch` from seven fields and no `tickets` (`recorder.py:234-237` on `35045636`), so `write_batch` always writes the empty default `TicketBatch` (`store.py:359`).
  - The registry's findings are counted only in `TicketRegistry.tally()` (`tickets.py:320-322`) and the hand-overs only in `AdmissionService.off_loop_checks()` (`service.py:254-256`). A restart loses both. #1604 property 8 asks for a service-written durable record whose producer and consumer markers the report counts on the live vessel.
- The two offer points exist:
  - `hold` takes `issued` from `issue` or `issue_child` and sets the carrier (`service.py:182-191`);
  - `_check_ticket` calls `self._tickets.check(...)`, discards its finding, then counts `off_loop` (`service.py:236-240`).
- M3d3b1's register R53: `ticket_findings`'s per-day bound assumes a work kind in `WORK_KINDS` or empty and an `off_loop` that is a bool. The store does not check either (`store.py:523-524`), and `TicketFinding.__post_init__` checks only the operation and code, by membership (`tickets.py:158-160`).
- M3d3b1's R52 bullet (from its A1-40 and A2): `write_batch` builds the ticket rows before its `try` (`store.py:526-527`) and runs them in the verdicts' transaction (`:551-561`). So a ticket part that raises fails the verdict part too, and `_restore` (`recorder.py:250-264`) would add the part back for the next flush. A hand-built finding whose `ticket_id` is not a `str` makes `persisted_finding` raise at `_ISSUED_ID.fullmatch` (`store.py:376-377`). Such a part would hold the verdict record back on every flush.
- Hidden pins this slice meets:
  - P13 pins `COUNTER_NAMES[-2:]` (`tests/test_ad1346_admission_shadow_parity.py:455`);
  - R1 compares `counters()` with `dict.fromkeys(COUNTER_NAMES, 0) | {...}` (`tests/test_ad1346_admission_shadow_recorder.py:171`), which holds for appended zeros;
  - T14 pins `recorder.py`'s imports (`tests/test_ad1346_admission_service.py:100-103`);
  - T13 pins `AdmissionService`'s attributes (`:493-496`; this slice adds none);
  - the SRP rule's method count (`scripts/check_architecture_principles.py:188`, `:559-564`).

## 2. Solution

- **The offer.** `ShadowRecorder.offer_ticket(finding, *, off_loop)` checks the finding (D151), counts it under (hour, operation, code, work kind, `off_loop`), and keeps a sample of every code except `ticket_issued` and `ticket_live`, `ticket_missing` in a buffer of its own. It awaits nothing and does no I/O.
- **The writer.** `_flush` detaches the pending work-ticket part as a `TicketBatch` into the batch's `tickets` field, and counts `ticket_written` when the write commits. `_restore` adds the part back within the two buffers. `_pending` counts it. `start` marks the hour for a work-ticket marker row.
- **The failing part (D150).** When a write raises an `Exception` and its work-ticket part holds a finding count or a sample, `_flush` writes the batch again at once. The second write replaces those counts and samples with dropped counts in the work-ticket markers. If it raises too, the batch is put back whole.
- **The offer points (D152).** `hold` offers the issue's finding before it sets the carrier. `_check_ticket` offers the check's finding after the off-loop count.
- **Stop.** The shutdown order is unchanged. `stop`'s warning counts the work-ticket findings and samples it could not write.

## 3. Decisions (numbered after M3d3b1's D137 to D148)

- **D149 One slice** (refines R52's scope).
  - 21 pairs and 1 new file, against M3d3b1's 27 and 1 and M3d3a's 33 and 1.
  - Rejected: recorder first, offers second (a second review of a writer with no producer, as M3d3b1 already had).
- **D150 A work-ticket part that raises does not hold the verdicts back** (answers M3d3b1's R52 bullet). Options, ranked:
  1. **Chosen: a second write at once with the ticket rows counted as dropped.** When `write_batch` raises an `Exception` and `batch.tickets` holds a finding count, a sample or a missing sample, `_flush` calls `_write_without_ticket_rows(batch)`. That writes `replace(batch, tickets=_as_dropped(batch.tickets))`. In `_as_dropped`'s part, the offered counts are kept, each finding count is added to its hour's dropped count, each sample adds one to its hour's samples-dropped count, and no finding count or sample remains.
     - If that write commits, the verdicts and the work-ticket markers are in the file, and `ticket_dropped` and `ticket_samples_dropped` count what was lost.
     - If it raises an `Exception`, the original batch is put back whole by `_restore`. "Whole": a detached part never holds more samples than its buffer, and `_restore` keeps the batch's samples first, so only offers made during the writes can overflow (TO6).
     - A `BaseException` that is not an `Exception` puts the batch back and propagates; the first write's failure is then not counted. No test raises one (§10, "Expected to survive").
     - The other direction is not bounded: a verdict part that raises still holds the ticket part back (register R62).
  2. Rejected: `offer_ticket` checks every field so that no part can raise. It depends on a complete list of what `persisted_finding`, `json.dumps` and SQLite's binding can raise. That list already misses a lone-surrogate id (register R60), and a later store change reopens it. The R53 checks are kept for the bound, not for this.
  3. Rejected: a separate transaction for the ticket part. It reverses D140's one transaction, changes M3d3b1's store after its review, and a poison part still retries on every flush and is never written.
  4. Rejected: never restoring a ticket part whose write raised. It loses the ticket part on every failed write, an outage included, while the verdicts are kept; the verdicts are still held back for that flush.
  5. Considered, deferred: halving the ticket part until the failing sample is isolated, the shape of AWS Lambda's `BisectBatchOnFunctionError` (§13). It costs up to log2(n) writes per flush for a cause no `src` producer reaches.
  - The cost of the choice is register R59 (a failure that clears between two writes drops one flush's ticket rows, counted) and R64.
- **D151 The offer's contract** (refines D140; closes register R53 for the recorder's writes).
  - Signature: `offer_ticket(finding: TicketFinding, *, off_loop: bool) -> None`.
  - Once `stop` began it counts `ticket_late` and checks and keeps nothing (as `offer` counts `late`).
  - Otherwise, before counting, it raises:
    - `TypeError` for a `finding` that is not an exact `TicketFinding`, or an `off_loop` that is not an exact `bool`;
    - `ValueError` for an operation, code or work kind that is not an exact `str`, or a work kind outside `WORK_KINDS` and `""` (`_OFFERED_WORK_KINDS`).
    - `__post_init__` already checks the operation's and code's membership.
  - With that, every pending key has an operation in `TICKET_OPERATIONS` (3), a code in `TICKET_REASON_CODES` (12), a work kind in `WORK_KINDS` plus `""` (12 + 1) and a bool (2). That is M3d3b1's 936 rows per UTC day for the keys this recorder writes.
  - Outcomes:
    - `ticket_issued` and `ticket_live` are counted and never sampled (`_COUNTED_ONLY`, D138);
    - `ticket_missing` is sampled into `_ticket_missing` within `TICKET_MISSING_BUFFER_LIMIT` (= `TICKET_MISSING_RING_SIZE`, 1,000);
    - every other code is sampled into `_ticket_samples` within `TICKET_SAMPLE_BUFFER_LIMIT` (= `TICKET_SAMPLE_RING_SIZE`, 5,000);
    - a new key beyond `PENDING_KEY_LIMIT` is counted as `ticket_dropped`, per hour and in total, and not sampled;
    - a sample beyond its buffer is counted as `ticket_samples_dropped`, per hour and in total.
  - The ids are digested only when written (`persisted_finding`, M3d3b1's D144). The recorder holds the finding as offered, in memory.
  - Fail open: an offer that raises an `Exception` is counted once in the service's `failures` (D152).
  - Rejected:
    - a sixth counter for refused findings (silent, and outside R52's five);
    - inferring `off_loop` in the recorder (only the service knows a check was handed over).
- **D152 Who offers, where, and on which thread** (refines D140).
  - `hold`: `if self._recorder is not None: self._recorder.offer_ticket(issued.finding, off_loop=False)`, after the issue and before `CURRENT_TICKET.set`. An offer that raises therefore leaves the carrier as it was. For an `Exception`, `hold` returns `NO_HOLD`, and an entry the issue added stays registered (register R63). This adds no path to register R45.
  - `_check_ticket`: `finding = self._tickets.check(...)`, the off-loop count, then `self._recorder.offer_ticket(finding, off_loop=off_loop)`. A raising offer leaves the check counted in the registry's tally.
  - `self._recorder` is compared with None, as `shadow` does (`service.py:147` on `35045636`).
  - Thread: each offer runs in the same function, on the same thread, as the registry call whose finding it offers.
    - In the runtime the sink checks run on the service's loop (D128). `ProbOSRuntime.start` starts the recorder's flusher and builds the service with `loop=asyncio.get_running_loop()` in the same coroutine (`runtime.py:2936-2937`, `:2959`), so the sink offers and the flusher share a thread.
    - `hold` runs on its entry's thread (register R58).
  - The recorder takes no lock, as `offer` never has.
  - Rejected:
    - a registry hook (couples the authority to I/O; `tickets.py` is held to the decision files' rules by T14);
    - offers from `hold_at` or `check_at` (they receive no finding: `check_ticket` returns None).
- **D153 The markers and the crash window** (refines D141; M3d3b1's blind spot 9).
  - Per (boot, hour):
    - `offered`: offers accepted, not late;
    - `written`: findings a committed write added to `ticket_findings`;
    - `dropped`: new keys beyond the limit, plus D150's dropped counts;
    - `samples_dropped`: buffer overflow at the offer and at `_restore`, plus D150's.
  - Once every pending count of a (boot, hour) is committed, offered = written + dropped there. `ticket_late` stays in memory. TO4, TO5, TO6 and TO10 check the identity on the cases they build.
  - `start` marks its hour for a work-ticket marker row (zeros), as it does for the verdict markers. So every boot whose first write succeeded is listed by `ticket_markers_by_boot`.
  - **The crash window.** The producer count is persisted in the transaction of the counts it describes, so a process that ends without `stop` loses both and no marker shows it. The loss is what was pending: up to `FLUSH_INTERVAL_SECONDS` of offers, more after failed writes. The property 8 report (M3e) is to:
    - list the boots of `ticket_markers_by_boot`;
    - count as possible crash windows the boots whose end AD-820 did not mark clean (`shutdown_integrity.py:15-24`: the next start refuses unless `--force-unclean`);
    - state the bound above for each.
    - AD-820's marker is written before the recorder stops (`startup/shutdown.py:1405-1418` and `:1497-1500` on `35045636`), so an end between the two is not flagged (register R61).
  - Rejected:
    - a clean-stop row (a persisted-schema change to M3d3b1's tables, for M3e if the report needs it);
    - writing `offered` ahead of its counts (I/O on the hot path, or a second transaction per flush).
- **D154 The stop path.**
  - The order in `startup/shutdown.py` is unchanged: `close` the service, `stop` the recorder, `stop` the store (`:1494-1506` on `35045636`).
  - `_pending` includes the work-ticket part, so `stop` flushes it, at most `STOP_FLUSH_ATTEMPTS` times. Each flush writes at most twice (D150).
  - The warning carries four counts: pending verdicts, samples, work-ticket findings, and work-ticket samples of both buffers.
  - After `close`, neither offer point reaches the recorder (`hold` returns before issuing, `_check_ticket` before checking). On the runtime's path, `ticket_late` can count only an offer from a `hold` or check that passed the closed test before `close` and reached the recorder after `stop` began.
  - Rejected: a work-ticket stop step of its own (a second lifecycle step for one transaction).
- **D155 The chain test and the boot test.**
  - TO10 is the chain: the real run entry (`WorkItemAgenticExecutor.run` with a scripted body, as SK5 and SK6), a delegated child holding a child ticket, a Captain's stop on the delegating agent, the next model and tool calls of the child and then of the parent, `recorder.stop()`, and the report's `ticket_` queries on a `mode=ro` connection. It shows `ticket_revoked` at both effects (two each), samples with digested ticket and parent ids and the stop's id, no raw id in any ring row, and markers offered equal to written (10).
  - TO11 is the wiring: a boot with an `OpenAICompatibleClient` subclass that starts no health probe and answers with a canned response (SK9's), one model call, `runtime.stop()`, then a `model_call`/`ticket_missing` row and the boot's marker row with offered equal to written in the store.
  - Rejected: the whole chain on a boot (an agentic run needs a scripted body, which a boot cannot take).
- **D156 The cost with the recorder** (D146's method; #1604 property 7).
  - Run by the orchestrator on M1's stage, before the review, on the Captain's Windows host, CPython 3.12.13.
  - D132's setup, timing and variants (a) to (d), each with `recorder=ShadowRecorder(store)` over an `AdmissionShadowStore` started in a temporary directory. The recorder is not started, and a fresh registry and recorder are built per round.
  - Report each median and 99th percentile beside D132's figures without a recorder, as recorded on #1604 and in M3d3a's DECISIONS bullet. M3d3a's record gives the medians (c) 5.0 to 5.1 µs and (a) 9.0 to 9.2 µs.
  - In (d) each check offers `ticket_missing`: the first 1,000 offers of a round keep a sample and later ones count a dropped sample. Report which path dominates. In (a) the service also offers a verdict per iteration.
  - Also report the time of one `write_batch` of one round's work-ticket part, 20 times (the flusher's cost, off the hot path).
  - Prediction: (c) and (d) each grow by less than 1.5 µs median, and (a) and (b) by less than 3 µs. No 99th percentile is predicted.
- **D157 Census and structure pins.**
  - `ShadowRecorder`: 12 direct methods before, 14 after (`offer_ticket`, `_write_without_ticket_rows`), against the trigger above 15. `_as_dropped` and `_first` are module functions. Its span grows from 196 lines (`recorder.py:90-285` on `35045636`) to 301, against 500 (both counts and the span by `ast` on the pre-build run of M1's stage; `recorder.py` grows from 285 to 456 lines).
  - `AdmissionService` gains no method and no attribute.
  - T14's `recorder.py` allowlist gains `dataclasses` and `probos.admission.tickets`; `service.py`'s is unchanged.
  - `check_store_registry.py`: no table, store or connection is added.
  - The seam census (`tests/fixtures/ad1343_seam_census.py:35-42`) records no `offer`-style callee, and no `shadow_at`, `hold_at` or `check_at` call is added.
  - P13 pins M3c's two names by position (`COUNTER_NAMES[6:8]`), and TO12 pins the five appended names (`[8:]`).
- **D158 The clock-reset rule** (refines D147).
  - During the shadow period, from this slice's deploy, a fix restarts the 7 days for the sink records when it changes which findings are kept or under which key. That covers:
    - `offer_ticket`'s checks, key, `_COUNTED_ONLY`, the buffer choice and limits;
    - the two offer statements;
    - `_flush`'s detach;
    - D150's condition and `_as_dropped`;
    - `_restore`'s work-ticket part;
    - M3d3b1's work-ticket rows and prune.
  - A fix to the markers' arithmetic, the start mark, the stop warning, the counters, a report query or `ticket_digest` restarts nothing; property 8's marker counts are then taken from boots after that fix.
  - All of M3d precedes the M3e deploy that starts the period, so no fix in this slice's review restarts anything.
- **D159 Left out.**
  - The property 8 and property 5 reports themselves, the crash-window count (D153) and the system-principal census: M3e.
  - Counting `TicketHold.end`'s passed-over failures (register R41): M3e.
  - A repair of `ticket_digest` for lone surrogates (register R60).
  - Isolating a failing sample within a part (D150, option 5).

## 4. Milestones and focused gates

| Milestone | Files | Focused gate |
|---|---|---|
| M1 | `src/probos/admission/recorder.py`, `src/probos/admission/service.py`, `tests/test_ad1346_admission_shadow_parity.py`, `tests/test_ad1346_admission_service.py` | `pytest tests/test_ad1346_admission_shadow_recorder.py tests/test_ad1346_admission_shadow_parity.py tests/test_ad1346_admission_shadow_store.py tests/test_ad1346_admission_shadow_report.py tests/test_ad1346_admission_shadow_boot.py tests/test_ad1346_admission_shadow_switch.py tests/test_ad1346_admission_service.py tests/test_ad1346_admission_service_boot.py tests/test_ad1346_admission_tickets.py tests/test_ad1346_admission_ticket_issue.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_ticket_record.py tests/test_ad1346_admission_shadow_seams.py tests/test_ad1256_store_registry.py tests/test_issue1419_failed_start_rollback.py -n 0`; `python -P scripts/check_architecture_principles.py --check`; `python -P scripts/check_store_registry.py --check`; then D156's cost run |
| M2 | new `tests/test_ad1346_admission_ticket_offers.py`; `tests/test_ad1346_admission_ticket_record.py` (docstring) | `git add` the new file, then `pytest tests/test_ad1346_admission_ticket_offers.py tests/test_ad1346_admission_ticket_record.py tests/test_ad1346_admission_shadow_recorder.py -n 0`; `pytest tests/test_ad1346_admission_ticket_offers.py --collect-only -q -p no:cacheprovider -n 0` (record the count) |
| M3 | `PROGRESS.md`, `DECISIONS.md`; regenerated `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | `python -P scripts/gen_ad_ledger.py`, then `python -P scripts/gen_ad_ledger.py --check`, then `pytest tests/test_ad1184_ad_ledger.py -n 0` |

## 5. Consumers of every value this changes

- **`ShadowRecorder.offer_ticket`.**
  - Called in `src` by `AdmissionService.hold` and `AdmissionService._check_ticket` only (§15's grep).
  - Called directly by the new test file (TO1, TO2, TO4 to TO7, and `_ThreadRecordingRecorder`'s override through `super()`) and overridden there by `_ThreadRecordingRecorder` (TO8) and `_RaisingTicketRecorder` (TO9).
  - TO3 reads its AST.
- **`COUNTER_NAMES`** (five names appended). Read in `src` by `__init__` only, whose totals `counters` copies. R1 compares `counters()` with `dict.fromkeys(COUNTER_NAMES, 0) | {...}` (unchanged: the new totals are zero there). P13 pins `[6:8]` (M1-16), and the new file pins `[8:]` and builds expected counters from it.
- **`TICKET_SAMPLE_BUFFER_LIMIT`, `TICKET_MISSING_BUFFER_LIMIT`.** Read at call time by `offer_ticket` and `_restore`. The new file patches them (both in TO4 and TO6, the sample buffer's in TO1 and TO5) and pins their values (TO12).
- **`ShadowBatch.tickets`.** Now filled by `_flush`, read and replaced by `_write_without_ticket_rows`, read by `write_batch` and `_restore`. Every other builder of a `ShadowBatch` (tests, D143's check) is unchanged.
- **`TicketBatch`, `TicketSample`.** Now built in `src` by `recorder.py` (`TicketBatch` in `_flush` and `_as_dropped`, `TicketSample` in `offer_ticket`), besides `ShadowBatch`'s default `TicketBatch` (`store.py`), M3d3b1's test file and D143's check.
- **The four `ticket_` tables.** Now written by the recorder through `write_batch` on a vessel. Their readers in `src` (the report's queries and `prune`) are unchanged; the new file reads them too.
- **`AdmissionService.hold` and `_check_ticket`.** Their return values, the carrier, `failures`, `off_loop_checks` and the registry's tally are unchanged for a service built with no recorder. With a recorder, `failures` also counts an offer that raises an `Exception` (TO9). Callers in `src`: `seam.hold_at` at three entries and `check_ticket` from the two sinks. Tests reach them directly or through an entry, a sink or a boot; among them M3d2's issue tests, M3d3a's sink tests and TO8 to TO11.
- **`stop`'s warning.** Read by people and by TO7's `record.args`; no test reads its message text (Absence Verified, on `35045636`).

## 6. Tests

| File | M | Cases | What |
|---|---|---|---|
| `tests/test_ad1346_admission_ticket_offers.py` | M2 | 12 (collected on the pre-build run; A1 adds none; M2's gate records the count again) | TO1 to TO12: real `AdmissionShadowStore` under `tmp_path`, real `IdentityService`, `AgentStopService` and `TicketRegistry`, the real run entry, a real `ToolRegistry`, the real gateway with a canned answer, one boot |
| `tests/test_ad1346_admission_shadow_parity.py` | M1 | unchanged count | P13's `COUNTER_NAMES` pin by position |
| `tests/test_ad1346_admission_service.py` | M1 | unchanged count | T14's `recorder.py` allowlist and docstring |
| `tests/test_ad1346_admission_ticket_record.py` | M2 | unchanged count | the module docstring's sentence on the recorder |

## 7. The contract

### 7.1 M1: `src/probos/admission/recorder.py`

**M1-01** (module docstring)

SEARCH:
```
pending (register R10 says when those exceed ``PENDING_KEY_LIMIT``). A flush that raises an
``Exception`` leaves the flusher running and is counted in memory as ``flush_errors`` (R1); a
``BaseException`` that is not an ``Exception`` ends it.
"""
```
REPLACE:
```
pending (register R10 says when those exceed ``PENDING_KEY_LIMIT``). A flush that raises an
``Exception`` leaves the flusher running and is counted in memory as ``flush_errors`` (R1); a
``BaseException`` that is not an ``Exception`` ends it.

AD-1346 M3d3b2: ``offer_ticket`` takes one ``TicketFinding`` that the ticket registry answered for an issue or a sink
check, and whether that check was handed to the service's loop from elsewhere (``off_loop``). Once ``stop`` began it
counts the offer in memory as ``ticket_late`` and checks and keeps nothing. Otherwise, before it counts, it raises
``TypeError`` for a finding that is not an exact ``TicketFinding`` or an ``off_loop`` that is not an exact ``bool``, and
``ValueError`` for a finding whose operation, code or work kind is not an exact ``str`` or whose work kind is neither in
``WORK_KINDS`` nor empty (register R53). It counts an accepted finding by (hour, operation, code, work kind,
``off_loop``) and keeps it as a sample unless its code is ``ticket_issued`` or ``ticket_live``: a ``ticket_missing``
sample within ``TICKET_MISSING_BUFFER_LIMIT`` pending ones, any other within ``TICKET_SAMPLE_BUFFER_LIMIT``. As for
verdicts, a finding that needs a new pending key beyond ``PENDING_KEY_LIMIT`` is counted as ``ticket_dropped`` and not
sampled, and a sample beyond its buffer is counted as ``ticket_samples_dropped``. The work-ticket markers' producer
count is the findings offered and their consumer count the findings a committed write added to ``ticket_findings``;
``start`` marks its hour for a work-ticket marker row too.

A flush writes the work-ticket part in the transaction of the verdicts (D140). When that write raises an ``Exception``
and the part holds a finding count or a sample, the flush writes the batch again at once with each such count and
sample counted as dropped in the work-ticket markers in place of its row (D150), so the second write holds no finding
count and no sample; when that write raises too, the batch is put back whole. Any other batch whose write raised is put
back whole, as before. ``offer`` and ``offer_ticket`` take no lock: each runs on its caller's thread, and the flusher on
the loop that ran ``start``. Totals and pending counts are this recorder's: a new recorder starts from none.
"""
```

**M1-02** (imports)

SEARCH:
```
import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Final

from probos.admission.store import (
    DAY_SECONDS,
    DISAGREEMENT_RING_SIZE,
    SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    ShadowDisagreement,
    ShadowSample,
    utc_hour,
)
from probos.admission.taxonomy import LATENCY_BUCKETS, OUTCOME_ADMIT, OUTCOME_WOULD_REFUSE, TODAY_REFUSE
```
REPLACE:
```
import asyncio
import logging
import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final

from probos.admission.store import (
    DAY_SECONDS,
    DISAGREEMENT_RING_SIZE,
    SAMPLE_RING_SIZE,
    TICKET_MISSING_RING_SIZE,
    TICKET_SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    ShadowDisagreement,
    ShadowSample,
    TicketBatch,
    TicketSample,
    utc_hour,
)
from probos.admission.taxonomy import (
    LATENCY_BUCKETS,
    OUTCOME_ADMIT,
    OUTCOME_WOULD_REFUSE,
    TICKET_ISSUED,
    TICKET_LIVE,
    TICKET_MISSING,
    TODAY_REFUSE,
    WORK_KINDS,
)
from probos.admission.tickets import TicketFinding
```

**M1-03** (constants)

SEARCH:
```
#: AD-1346 M3c (D58): pending disagreement samples kept between two writes that succeed (the store's ring size).
DISAGREEMENT_BUFFER_LIMIT: Final = DISAGREEMENT_RING_SIZE
#: The totals ``counters`` returns, in order. Append-only; AD-1346 M3c appended the last two.
COUNTER_NAMES: Final[tuple[str, ...]] = (
    "offered", "written", "dropped", "samples_dropped", "late", "flush_failures", "disagreement_samples_dropped",
    "flush_errors",
)
_HOUR_SECONDS: Final = 3_600
```
REPLACE:
```
#: AD-1346 M3c (D58): pending disagreement samples kept between two writes that succeed (the store's ring size).
DISAGREEMENT_BUFFER_LIMIT: Final = DISAGREEMENT_RING_SIZE
#: AD-1346 M3d3b2 (D151): pending work-ticket samples other than ``ticket_missing`` kept between two writes that
#: succeed (the ``ticket_samples`` ring's size).
TICKET_SAMPLE_BUFFER_LIMIT: Final = TICKET_SAMPLE_RING_SIZE
#: AD-1346 M3d3b2 (D151): pending ``ticket_missing`` samples kept between two writes that succeed (the
#: ``ticket_missing_samples`` ring's size).
TICKET_MISSING_BUFFER_LIMIT: Final = TICKET_MISSING_RING_SIZE
#: The totals ``counters`` returns, in order. Append-only; AD-1346 M3c appended ``disagreement_samples_dropped`` and
#: ``flush_errors``, and AD-1346 M3d3b2 the five ``ticket_`` totals.
COUNTER_NAMES: Final[tuple[str, ...]] = (
    "offered", "written", "dropped", "samples_dropped", "late", "flush_failures", "disagreement_samples_dropped",
    "flush_errors", "ticket_offered", "ticket_written", "ticket_dropped", "ticket_samples_dropped", "ticket_late",
)
_HOUR_SECONDS: Final = 3_600
#: AD-1346 M3d3b2 (D151, register R53): the work kinds ``offer_ticket`` takes: ``WORK_KINDS`` and the empty one that a
#: finding with no registered ticket carries.
_OFFERED_WORK_KINDS: Final = frozenset((*WORK_KINDS, ""))
#: AD-1346 M3d3b2 (D138, D151): the codes ``offer_ticket`` counts and never samples.
_COUNTED_ONLY: Final = frozenset({TICKET_ISSUED, TICKET_LIVE})
```

**M1-04** (module helpers)

SEARCH:
```
def is_disagreement(outcome: str, today_outcome: str) -> bool:
    """AD-1346 M3c (D58): the shadow outcome and the site's own differ: a would-refuse where the site admitted, or an admit where it refused."""
    return (outcome == OUTCOME_WOULD_REFUSE) != (today_outcome == TODAY_REFUSE)
```
REPLACE:
```
def is_disagreement(outcome: str, today_outcome: str) -> bool:
    """AD-1346 M3c (D58): the shadow outcome and the site's own differ: a would-refuse where the site admitted, or an admit where it refused."""
    return (outcome == OUTCOME_WOULD_REFUSE) != (today_outcome == TODAY_REFUSE)


def _as_dropped(tickets: TicketBatch) -> TicketBatch:
    """AD-1346 M3d3b2 (D150): ``tickets`` with no finding count and no sample. Its offered counts are kept, its dropped
    counts gain each finding count by hour, and its samples-dropped counts gain one for each sample by hour."""
    dropped = dict(tickets.dropped)
    for (hour, _operation, _code, _work_kind, _off_loop), count in tickets.findings.items():
        dropped[hour] = dropped.get(hour, 0) + count
    samples_dropped = dict(tickets.samples_dropped)
    for sample in tickets.samples + tickets.missing:
        samples_dropped[sample.hour] = samples_dropped.get(sample.hour, 0) + 1
    return TicketBatch(offered=dict(tickets.offered), dropped=dropped, samples_dropped=samples_dropped)


def _first(samples: list[TicketSample], limit: int, dropped: dict[str, int]) -> list[TicketSample]:
    """AD-1346 M3d3b2: the first ``limit`` of ``samples``; each later one is counted in ``dropped`` under its hour."""
    for sample in samples[limit:]:
        dropped[sample.hour] = dropped.get(sample.hour, 0) + 1
    return samples[:limit]
```

**M1-05** (`__init__`)

SEARCH:
```
        self._dropped: dict[str, int] = {}
        self._samples_dropped: dict[str, int] = {}
        self._totals: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
```
REPLACE:
```
        self._dropped: dict[str, int] = {}
        self._samples_dropped: dict[str, int] = {}
        # AD-1346 M3d3b2 (D151): the pending work-ticket part, which _flush detaches as one TicketBatch
        self._ticket_findings: dict[tuple[str, str, str, str, bool], int] = {}
        self._ticket_samples: list[TicketSample] = []
        self._ticket_missing: list[TicketSample] = []
        self._ticket_offered: dict[str, int] = {}
        self._ticket_dropped: dict[str, int] = {}
        self._ticket_samples_dropped: dict[str, int] = {}
        self._totals: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
```

**M1-06** (`offer_ticket`, after `offer`)

SEARCH:
```
            self._totals["samples_dropped"] += 1
            self._samples_dropped[hour] = self._samples_dropped.get(hour, 0) + 1

    def _hour_of(self, now: float) -> str:
```
REPLACE:
```
            self._totals["samples_dropped"] += 1
            self._samples_dropped[hour] = self._samples_dropped.get(hour, 0) + 1

    def offer_ticket(self, finding: TicketFinding, *, off_loop: bool) -> None:
        """AD-1346 M3d3b2 (D151): count one work-ticket finding in memory and, within the bounds below, keep it as a sample unless its code is ``ticket_issued`` or ``ticket_live``.

        Once ``stop`` began it counts the offer as ticket_late and checks and keeps nothing. Otherwise, before it counts,
        it raises ``TypeError`` for a ``finding`` that is not an exact ``TicketFinding`` or an ``off_loop`` that is not
        an exact ``bool``, and ``ValueError`` for a finding whose operation, code or work kind is not an exact ``str``
        or whose work kind is neither in ``WORK_KINDS`` nor empty (register R53). A finding that needs a new pending
        key beyond ``PENDING_KEY_LIMIT`` is counted as ticket_dropped and is not sampled. A ``ticket_missing`` sample
        beyond ``TICKET_MISSING_BUFFER_LIMIT`` pending ones, or any other beyond ``TICKET_SAMPLE_BUFFER_LIMIT``, is not
        kept and is counted as ticket_samples_dropped. It awaits nothing and does no I/O.
        """
        if self._stopping:
            self._totals["ticket_late"] += 1
            return
        if type(finding) is not TicketFinding or type(off_loop) is not bool:
            raise TypeError("AD-1346 M3d3b2: offer_ticket takes an exact TicketFinding and an exact bool off_loop")
        operation, code, work_kind = finding.operation, finding.code, finding.work_kind
        exact = type(operation) is str and type(code) is str and type(work_kind) is str
        if not exact or work_kind not in _OFFERED_WORK_KINDS:
            raise ValueError(
                "AD-1346 M3d3b2: a work-ticket finding's operation, code and work kind are exact str, and its work kind "
                "is in WORK_KINDS or empty"
            )
        now = self._wall_clock()
        hour = self._hour_of(now)
        self._totals["ticket_offered"] += 1
        self._ticket_offered[hour] = self._ticket_offered.get(hour, 0) + 1
        key = (hour, operation, code, work_kind, off_loop)
        if key in self._ticket_findings:
            self._ticket_findings[key] += 1
        elif len(self._ticket_findings) < PENDING_KEY_LIMIT:
            self._ticket_findings[key] = 1
        else:
            self._totals["ticket_dropped"] += 1
            self._ticket_dropped[hour] = self._ticket_dropped.get(hour, 0) + 1
            return
        if code in _COUNTED_ONLY:
            return
        missing = code == TICKET_MISSING
        buffer = self._ticket_missing if missing else self._ticket_samples
        if len(buffer) < (TICKET_MISSING_BUFFER_LIMIT if missing else TICKET_SAMPLE_BUFFER_LIMIT):
            buffer.append(TicketSample(hour, now, finding, off_loop))
        else:
            self._totals["ticket_samples_dropped"] += 1
            self._ticket_samples_dropped[hour] = self._ticket_samples_dropped.get(hour, 0) + 1

    def _hour_of(self, now: float) -> str:
```

**M1-07** (`start`)

SEARCH:
```
    def start(self) -> None:
        """Mark the current hour for this boot's marker row and start the flusher task.

        Raises ``RuntimeError`` when it has already started or ``stop`` began.
        """
        if self._task is not None or self._stopping:
            raise RuntimeError("AD-1346 M3b: a shadow recorder starts once")
        hour = self._hour_of(self._wall_clock())
        self._offered.setdefault(hour, 0)
        self._task = asyncio.create_task(self._run(), name=FLUSHER_TASK_NAME)
```
REPLACE:
```
    def start(self) -> None:
        """Mark the current hour for this boot's marker row and, from AD-1346 M3d3b2, its work-ticket marker row, and start the flusher task.

        Raises ``RuntimeError`` when it has already started or ``stop`` began.
        """
        if self._task is not None or self._stopping:
            raise RuntimeError("AD-1346 M3b: a shadow recorder starts once")
        hour = self._hour_of(self._wall_clock())
        self._offered.setdefault(hour, 0)
        self._ticket_offered.setdefault(hour, 0)  # AD-1346 M3d3b2 (D153): the boot's work-ticket marker row too
        self._task = asyncio.create_task(self._run(), name=FLUSHER_TASK_NAME)
```

**M1-08** (`_run`'s comment)

SEARCH:
```
                # A log call in _flush that raised (F-212's class) runs after any batch it detached was put
                # back (_restore precedes _failed); the next tick flushes again. Counted, not logged,
                # because the log call may be what raised.
```
REPLACE:
```
                # A log call in _flush that raised (F-212's class) runs after any batch it detached was put
                # back or written; the next tick flushes again. Counted, not logged, because the log call
                # may be what raised.
```

**M1-09** (`stop`'s docstring)

SEARCH:
```
    async def stop(self) -> None:
        """Refuse later offers, let the flusher end after its last flush, then flush what is still pending.

        It waits for the flusher without cancelling it, so this call interrupts no write. Then it
        flushes while anything is pending, at most ``STOP_FLUSH_ATTEMPTS`` times, and logs a warning
        naming what was not written. A flush that raises an ``Exception`` is logged by the flush,
        not raised here.
        """
```
REPLACE:
```
    async def stop(self) -> None:
        """Refuse later offers of verdicts and of work-ticket findings, let the flusher end after its last flush, then flush what is still pending.

        It waits for the flusher without cancelling it, so this call interrupts no write. Then it
        flushes while anything is pending, at most ``STOP_FLUSH_ATTEMPTS`` times (each flush writes at
        most twice, D150), and logs a warning with the counts of the verdicts, samples, work-ticket
        findings and work-ticket samples that were not written. A write that raises an ``Exception``
        is counted and logged by the flush; it is not raised here.
        """
```

**M1-10** (`stop`'s warning)

SEARCH:
```
        if self._pending():
            logger.warning(
                "AD-1346 M3b: %d shadow verdicts and %d samples were not written before the recorder stopped",
                sum(self._aggregates.values()), len(self._samples),
            )
```
REPLACE:
```
        if self._pending():
            logger.warning(
                "AD-1346 M3b, M3d3b2: %d shadow verdicts, %d samples, %d work-ticket findings and %d work-ticket "
                "samples were not written before the recorder stopped",
                sum(self._aggregates.values()), len(self._samples), sum(self._ticket_findings.values()),
                len(self._ticket_samples) + len(self._ticket_missing),
            )
```

**M1-11** (`_flush`'s write, the second write, `_restore`, `_pending`)

SEARCH:
```
        if not self._pending():
            return
        batch = ShadowBatch(
            self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped,
            parity=self._parity, disagreements=self._disagreements,
        )
        self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped = {}, [], {}, {}, {}
        self._parity, self._disagreements = {}, []
        try:
            written = await self._store.write_batch(self._boot_id, batch)
        except BaseException as exc:
            self._restore(batch)
            if not isinstance(exc, Exception):
                raise
            self._failed("write")
            return
        self._totals["written"] += written

    def _restore(self, batch: ShadowBatch) -> None:
        """Add a batch that was not written back to what is pending, keeping at most ``SAMPLE_BUFFER_LIMIT`` samples and ``DISAGREEMENT_BUFFER_LIMIT`` disagreements."""
        _add(self._aggregates, batch.aggregates)
        _add(self._offered, batch.offered)
        _add(self._dropped, batch.dropped)
        _add(self._samples_dropped, batch.samples_dropped)
        kept = batch.samples + self._samples
        for sample in kept[SAMPLE_BUFFER_LIMIT:]:
            self._totals["samples_dropped"] += 1
            self._samples_dropped[sample.hour] = self._samples_dropped.get(sample.hour, 0) + 1
        self._samples = kept[:SAMPLE_BUFFER_LIMIT]
        _add(self._parity, batch.parity)
        disagreements = batch.disagreements + self._disagreements
        self._totals["disagreement_samples_dropped"] += max(0, len(disagreements) - DISAGREEMENT_BUFFER_LIMIT)
        self._disagreements = disagreements[:DISAGREEMENT_BUFFER_LIMIT]

    def _pending(self) -> bool:
        return bool(
            self._aggregates or self._samples or self._offered or self._dropped or self._samples_dropped
            or self._parity or self._disagreements
        )
```
REPLACE:
```
        if not self._pending():
            return
        tickets = TicketBatch(
            self._ticket_findings, self._ticket_samples, self._ticket_missing, self._ticket_offered,
            self._ticket_dropped, self._ticket_samples_dropped,
        )
        batch = ShadowBatch(
            self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped,
            parity=self._parity, disagreements=self._disagreements, tickets=tickets,
        )
        self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped = {}, [], {}, {}, {}
        self._parity, self._disagreements = {}, []
        self._ticket_findings, self._ticket_samples, self._ticket_missing = {}, [], []
        self._ticket_offered, self._ticket_dropped, self._ticket_samples_dropped = {}, {}, {}
        try:
            written = await self._store.write_batch(self._boot_id, batch)
        except BaseException as exc:
            if isinstance(exc, Exception) and (tickets.findings or tickets.samples or tickets.missing):
                await self._write_without_ticket_rows(batch)  # D150: written without its ticket rows, or put back whole
                self._failed("write")
                return
            self._restore(batch)
            if not isinstance(exc, Exception):
                raise
            self._failed("write")
            return
        self._totals["written"] += written
        self._totals["ticket_written"] += sum(tickets.findings.values())

    async def _write_without_ticket_rows(self, batch: ShadowBatch) -> None:
        """AD-1346 M3d3b2 (D150): after a write of ``batch`` raised, write it again at once with its work-ticket finding
        counts and samples counted as dropped in its work-ticket markers in place of their rows.

        When that write raises too, ``batch`` is put back whole; an ``Exception`` is then counted and logged by
        ``_failed``, and a ``BaseException`` that is not an ``Exception`` propagates.
        """
        tickets = batch.tickets
        try:
            written = await self._store.write_batch(self._boot_id, replace(batch, tickets=_as_dropped(tickets)))
        except BaseException as exc:
            self._restore(batch)
            if not isinstance(exc, Exception):
                raise
            self._failed("write")
            return
        self._totals["written"] += written
        self._totals["ticket_dropped"] += sum(tickets.findings.values())
        self._totals["ticket_samples_dropped"] += len(tickets.samples) + len(tickets.missing)

    def _restore(self, batch: ShadowBatch) -> None:
        """Add a batch that was not written back to what is pending, keeping at most ``SAMPLE_BUFFER_LIMIT`` samples and ``DISAGREEMENT_BUFFER_LIMIT`` disagreements.

        AD-1346 M3d3b2: its work-ticket part too, keeping at most ``TICKET_SAMPLE_BUFFER_LIMIT`` and
        ``TICKET_MISSING_BUFFER_LIMIT`` samples, the batch's first; each sample beyond them is counted as
        ticket_samples_dropped.
        """
        _add(self._aggregates, batch.aggregates)
        _add(self._offered, batch.offered)
        _add(self._dropped, batch.dropped)
        _add(self._samples_dropped, batch.samples_dropped)
        kept = batch.samples + self._samples
        for sample in kept[SAMPLE_BUFFER_LIMIT:]:
            self._totals["samples_dropped"] += 1
            self._samples_dropped[sample.hour] = self._samples_dropped.get(sample.hour, 0) + 1
        self._samples = kept[:SAMPLE_BUFFER_LIMIT]
        _add(self._parity, batch.parity)
        disagreements = batch.disagreements + self._disagreements
        self._totals["disagreement_samples_dropped"] += max(0, len(disagreements) - DISAGREEMENT_BUFFER_LIMIT)
        self._disagreements = disagreements[:DISAGREEMENT_BUFFER_LIMIT]
        tickets = batch.tickets  # AD-1346 M3d3b2 (D150, D151): the work-ticket part, back within its two buffers
        _add(self._ticket_findings, tickets.findings)
        _add(self._ticket_offered, tickets.offered)
        _add(self._ticket_dropped, tickets.dropped)
        _add(self._ticket_samples_dropped, tickets.samples_dropped)
        samples, missing = tickets.samples + self._ticket_samples, tickets.missing + self._ticket_missing
        self._totals["ticket_samples_dropped"] += max(0, len(samples) - TICKET_SAMPLE_BUFFER_LIMIT)
        self._totals["ticket_samples_dropped"] += max(0, len(missing) - TICKET_MISSING_BUFFER_LIMIT)
        self._ticket_samples = _first(samples, TICKET_SAMPLE_BUFFER_LIMIT, self._ticket_samples_dropped)
        self._ticket_missing = _first(missing, TICKET_MISSING_BUFFER_LIMIT, self._ticket_samples_dropped)

    def _pending(self) -> bool:
        return bool(
            self._aggregates or self._samples or self._offered or self._dropped or self._samples_dropped
            or self._parity or self._disagreements
            or self._ticket_findings or self._ticket_samples or self._ticket_missing or self._ticket_offered
            or self._ticket_dropped or self._ticket_samples_dropped
        )
```

### 7.2 M1: `src/probos/admission/service.py`

**M1-12** (module docstring)

SEARCH:
```
AD-1346 M3d3a added ``check_ticket``: ``probos.admission.seam.check_at`` calls it at the tool sink and the model
gateway, and nothing is refused or persisted. A service built with an event loop checks on that loop: a sink on
another thread, or on another thread's loop, hands its check there with ``call_soon_threadsafe`` (D128). A sink check
that raises an ``Exception`` in ``_check_ticket`` is counted in ``failures`` and logged, as ``hold``'s is.
The service reads no configuration.
```
REPLACE:
```
AD-1346 M3d3a added ``check_ticket``: ``probos.admission.seam.check_at`` calls it at the tool sink and the model
gateway, and nothing is refused. A service built with an event loop checks on that loop: a sink on
another thread, or on another thread's loop, hands its check there with ``call_soon_threadsafe`` (D128). A sink check
that raises an ``Exception`` in ``_check_ticket`` is counted in ``failures`` and logged, as ``hold``'s is.
AD-1346 M3d3b2: a service built with a recorder also hands the finding of each issue and of each sink check that the
registry answers, in ``hold`` and in ``_check_ticket``, to ``ShadowRecorder.offer_ticket``, inside the same ``try`` and,
in ``hold``, before the carrier is set; an ``Exception`` from that offer is counted in ``failures`` and logged as the
rest of that ``try``'s are.
The service reads no configuration.
```

**M1-13** (`hold`'s docstring)

SEARCH:
```
        ticket when ``child is True`` and the carrier holds one, else a root (D111). The carrier then holds the new
        ticket, or None when the registry refused the issue and counted its finding (D114).
        An ``Exception`` raised here is counted in ``failures`` and logged; a
        ``BaseException`` that is not an ``Exception`` propagates.
        """
```
REPLACE:
```
        ticket when ``child is True`` and the carrier holds one, else a root (D111). The carrier then holds the new
        ticket, or None when the registry refused the issue and counted its finding (D114).
        AD-1346 M3d3b2 (D152): with a recorder, the issue's finding is offered to ``ShadowRecorder.offer_ticket`` before
        the carrier is set, so an offer that raises leaves the carrier as it was; for an ``Exception``, an entry the
        issue added stays registered and ``hold`` returns ``NO_HOLD``.
        An ``Exception`` raised here is counted in ``failures`` and logged; a
        ``BaseException`` that is not an ``Exception`` propagates.
        """
```

**M1-14** (`hold`'s offer)

SEARCH:
```
                issued = self._tickets.issue_child(
                    parent, principal_key=key, work_kind=work_kind, seam=seam, scope=_WORK_SCOPE, budget=_NO_CEILINGS,
                )
            token = CURRENT_TICKET.set(issued.ticket)
            return TicketHold(self._tickets, issued.ticket, token)
```
REPLACE:
```
                issued = self._tickets.issue_child(
                    parent, principal_key=key, work_kind=work_kind, seam=seam, scope=_WORK_SCOPE, budget=_NO_CEILINGS,
                )
            if self._recorder is not None:  # AD-1346 M3d3b2 (D152): before the carrier is set, so a raising offer leaves it
                self._recorder.offer_ticket(issued.finding, off_loop=False)
            token = CURRENT_TICKET.set(issued.ticket)
            return TicketHold(self._tickets, issued.ticket, token)
```

**M1-15** (`_check_ticket`'s docstring and offer)

SEARCH:
```
        compared is the key ``decide`` gives ``presented_id`` when that is a non-empty ``str``, else none. A check handed
        over from elsewhere is counted in ``off_loop_checks`` once answered. An ``Exception`` is counted in ``failures``
        and logged, as ``hold``'s is; a ``BaseException`` that is not an ``Exception`` propagates.
        """
        if self._closed or self._tickets is None:  # no registry, or closed (a check handed over before close included): nothing is checked
            return None
        try:
            key = resolve_principal(presented_id, self._identities).key if type(presented_id) is str and presented_id else ""
            self._tickets.check(ticket, effect=effect, presented_key=key)
            if off_loop:
                self._off_loop[effect] = self._off_loop.get(effect, 0) + 1
```
REPLACE:
```
        compared is the key ``decide`` gives ``presented_id`` when that is a non-empty ``str``, else none. A check handed
        over from elsewhere is counted in ``off_loop_checks`` once answered. AD-1346 M3d3b2 (D152): with a recorder, the
        finding is then offered to ``ShadowRecorder.offer_ticket`` with ``off_loop``, on the thread the check ran on.
        An ``Exception`` is counted in ``failures``
        and logged, as ``hold``'s is; a ``BaseException`` that is not an ``Exception`` propagates.
        """
        if self._closed or self._tickets is None:  # no registry, or closed (a check handed over before close included): nothing is checked
            return None
        try:
            key = resolve_principal(presented_id, self._identities).key if type(presented_id) is str and presented_id else ""
            finding = self._tickets.check(ticket, effect=effect, presented_key=key)
            if off_loop:
                self._off_loop[effect] = self._off_loop.get(effect, 0) + 1
            if self._recorder is not None:  # AD-1346 M3d3b2 (D152): after the off-loop count, on the thread of the check
                self._recorder.offer_ticket(finding, off_loop=off_loop)
```

### 7.3 M1: `tests/test_ad1346_admission_shadow_parity.py` (an M3d3b1-edited file)

**M1-16** (P13)

SEARCH:
```
    one_day = len(WORK_KINDS) * len(SEAMS) * len(TODAY_OUTCOMES) * len(REASON_CODES)
    assert one_day * AGGREGATE_RETENTION_DAYS < AGGREGATE_ROW_LIMIT, one_day
    assert recorder_module.COUNTER_NAMES[-2:] == ("disagreement_samples_dropped", "flush_errors")
```
REPLACE:
```
    one_day = len(WORK_KINDS) * len(SEAMS) * len(TODAY_OUTCOMES) * len(REASON_CODES)
    assert one_day * AGGREGATE_RETENTION_DAYS < AGGREGATE_ROW_LIMIT, one_day
    assert recorder_module.COUNTER_NAMES[6:8] == ("disagreement_samples_dropped", "flush_errors")  # AD-1346 M3d3b2 appended five after them
```

### 7.4 M1: `tests/test_ad1346_admission_service.py` (an M3d3b1-edited file)

**M1-17** (T14's `recorder.py` allowlist)

SEARCH:
```
    "recorder.py": {
        "__future__", "asyncio", "collections.abc", "logging", "time", "typing", "uuid", "probos.admission.record",
        "probos.admission.store", "probos.admission.taxonomy",
    },
```
REPLACE:
```
    "recorder.py": {
        "__future__", "asyncio", "collections.abc", "dataclasses", "logging", "time", "typing", "uuid",
        "probos.admission.record", "probos.admission.store", "probos.admission.taxonomy", "probos.admission.tickets",
    },
```

**M1-18** (T14's docstring)

SEARCH:
```
    ``call_soon_threadsafe``, neither of which awaits. AD-1346 M3d3b added ``hashlib``, ``re`` and
    ``probos.admission.tickets`` to ``store.py``'s."""
```
REPLACE:
```
    ``call_soon_threadsafe``, neither of which awaits. AD-1346 M3d3b added ``hashlib``, ``re`` and
    ``probos.admission.tickets`` to ``store.py``'s, and AD-1346 M3d3b2 ``dataclasses`` and ``probos.admission.tickets``
    to ``recorder.py``'s."""
```

### 7.5 (no further pairs in M1)

### 7.5.N New file: `tests/test_ad1346_admission_ticket_offers.py` (M2)

```python
"""AD-1346 M3d3b2 (#1604): the recorder's offers, the work ticket's findings written to ``admission_shadow.db``.

``AdmissionService.hold`` offers the finding of each issue the registry answers, and ``AdmissionService._check_ticket``
the finding of each sink check, to ``ShadowRecorder.offer_ticket``; the recorder writes them behind, in the
transaction of its verdicts. Every case but TO3 builds a real ``AdmissionShadowStore`` under ``tmp_path``, and the cases
that read one back do so with SQL or with the report's queries on a ``mode=ro`` connection.

- TO1  ``offer_ticket`` counts each finding by UTC day, operation, code, work kind and ``off_loop``, keeps no sample of
       ``ticket_issued`` or ``ticket_live``, keeps a ``ticket_missing`` sample in the missing ring and the others in
       ``ticket_samples``, each as ``persisted_finding`` JSON; the marker row counts five
       offered and five written. With no room in the sample buffer, one finding of each code drops a sample for every
       code but those two and ``ticket_missing``, and a finding of each work kind in ``WORK_KINDS`` and of the empty
       one is counted.
- TO2  it raises ``TypeError`` for an object that is not a ``TicketFinding``, for an instance of a subclass of it and
       for an ``off_loop`` of 1, and
       ``ValueError`` for an unknown work kind and for a ``str`` subclass operation, code or work kind, and counts and
       keeps none of them.
- TO3  ``offer_ticket`` is a plain function: no await, and none of the store, task, wait or I/O names R2 forbids
       ``offer`` to call.
- TO4  beyond ``PENDING_KEY_LIMIT`` pending keys a new key is dropped, counted and not sampled; each ring's buffer
       keeps its own limit and counts its overflow; an offer after ``stop`` began is counted as late and not written.
- TO5  a work-ticket part whose write raises (a hand-built finding whose ``ticket_id`` is None) is written again at once
       with its finding counts and the samples of both buffers counted as dropped in the work-ticket markers, beside the
       dropped counts it already held, and the verdicts are written by that second write; a part of counts only whose
       first write fails and whose second commits is written as dropped too (register R59), and so is a part whose two
       samples, one in each buffer, fall in two hours that held no dropped count, each counted once in its own hour.
- TO6  a batch whose two writes raise is put back whole, its own samples kept first within the two buffers, and written
       by the next flush; the marker rows of its two hours then hold every offer, the restored dropped counts and every
       overflow, each under the hour of its offer.
- TO7  ``stop`` logs each of the four failed writes and then a warning whose arguments count the verdicts, samples,
       work-ticket findings and work-ticket samples it could not write, four different counts in that order; a batch
       put back within both buffers counts no sample as dropped.
- TO8  the service offers the finding of each issue (a refused one included) and of each sink check, with
       ``off_loop`` for the check handed to its loop, each on the loop's thread.
- TO9  an offer that raises a ``RuntimeError`` is one counted failure: ``hold`` returns ``NO_HOLD`` with the carrier
       as it was and the issued entry registered, and each sink check whose offer raises counts one failure more, a
       handed-over one after its off-loop count.
- TO10 #1604 property 5, persisted: in the real run entry, after a Captain's stop on the delegating agent, the next
       model and tool calls of its delegated child and then its own count ``ticket_revoked``; after ``stop`` the report
       shows them by operation, their samples with digested ids and the stop's id, and the markers offered equal to
       written.
- TO11 the wiring: on a boot whose LLM client is an ``OpenAICompatibleClient``, after one model call and
       ``runtime.stop()``, the store holds a ``model_call`` ``ticket_missing`` count and the boot's marker row has
       offered equal to written and no finding dropped.
- TO12 ``COUNTER_NAMES`` appends the five ``ticket_`` totals, the two buffer limits are the ring sizes, and ``start``
       marks the boot's hour in the work-ticket markers.

TO8 and TO9 each run one sink check on a worker thread (``asyncio.to_thread``). TO11 boots a ``ProbOSRuntime`` with
``SystemConfig()`` and the naming ceremony, the proactive loop and QA turned off, and with a gateway that starts no
health probe and answers each request with a canned response in place of sending it, as
``tests/test_ad1346_admission_ticket_sinks.py`` does.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission import recorder as recorder_module
from probos.admission import tickets as tickets_module
from probos.admission.carrier import CURRENT_TICKET, NO_HOLD
from probos.admission.recorder import COUNTER_NAMES, ShadowRecorder
from probos.admission.report import open_read_only, run_query
from probos.admission.store import (
    STORE_FILENAME,
    TICKET_MISSING_RING_SIZE,
    TICKET_SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    persisted_finding,
    ticket_digest,
    utc_hour,
)
from probos.admission.taxonomy import SEAM_MODEL_CALL, TICKET_REASON_CODES, WORK_KINDS
from probos.admission.tickets import TicketFinding, TicketRegistry
from probos.agent_stop import SEAM_INTENT, SEAM_TOOL, AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests.fixtures.ad1343_seam_census import function
from tests.fixtures.ad1346_shadow import HOUR, T0, admit, refuse, rows

INSTANCE_ID = "ad1346-m3d3b2-ship"
VESSEL_NAME = "Ad1346m3d3b2"
AGENT_A = "ad1346-m3d3b2-agent-a"
AGENT_B = "ad1346-m3d3b2-agent-b"
RAW_ID = "0123456789abcdef" * 2  # the form of an id the registry issues
DAY = "2026-10-28"  # the UTC day of T0
_ABSENT = "ad1346_m3d3b2_absent"  # a tool id no registry holds: the tool sink answers "not found" and runs nothing
FINDINGS = (
    "SELECT day, operation, code, work_kind, off_loop, findings FROM ticket_findings "
    "ORDER BY operation, code, work_kind, off_loop"
)
MARKERS = "SELECT boot_id, hour, offered, written, dropped, samples_dropped FROM ticket_markers ORDER BY hour"


class _Clock:
    """An injected wall clock that only the test moves."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Kind(str):
    """A ``str`` subclass: it equals and hashes as the ``str`` it is built from, and it is not an exact ``str``."""

    __slots__ = ()


class _SubFinding(TicketFinding):
    """A ``TicketFinding`` subclass: it holds every field of one, and it is not an exact ``TicketFinding``."""

    __slots__ = ()


class _FailingStore(AdmissionShadowStore):
    """A real store whose first ``failures`` writes raise; the first of them calls ``during``, when it is set, before it
    raises."""

    def __init__(self, *, data_dir: Path, failures: int) -> None:
        super().__init__(data_dir=data_dir)
        self.failures = failures
        self.during: Callable[[], None] | None = None
        self.attempts = 0

    async def write_batch(self, boot_id: str, batch: ShadowBatch) -> int:
        self.attempts += 1
        if self.attempts <= self.failures:
            during, self.during = self.during, None
            if during is not None:
                during()
            raise OSError("INJECTED ticket record write failure")
        return await super().write_batch(boot_id, batch)


class _ThreadRecordingRecorder(ShadowRecorder):
    """A recorder that records the thread each ``offer_ticket`` runs on."""

    def __init__(self, store: AdmissionShadowStore, **kwargs: Any) -> None:
        super().__init__(store, **kwargs)
        self.threads: list[int] = []

    def offer_ticket(self, finding: TicketFinding, *, off_loop: bool) -> None:
        self.threads.append(threading.get_ident())
        super().offer_ticket(finding, off_loop=off_loop)


class _RaisingTicketRecorder(ShadowRecorder):
    """A recorder whose ``offer_ticket`` raises."""

    def offer_ticket(self, finding: TicketFinding, *, off_loop: bool) -> None:
        raise RuntimeError("INJECTED ticket offer failure")


class _OfflineGateway(OpenAICompatibleClient):
    """The model gateway with no endpoint: it starts no health probe and answers with a canned response where it would
    send the request."""

    async def start_health_probe(self, interval_seconds: float = 30.0, emit_fn: Any = None) -> None:
        return None

    async def _complete_inner(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="ad1346-m3d3b2", model="m", tier="standard")


class _ScriptedRun(WorkItemAgenticExecutor):
    """The real run entry (its stop check, shadow statement and hold) over a scripted body in place of the agentic loop."""

    def __init__(self, bodies: dict[str, Callable[[dict[str, Any]], Awaitable[str]]]) -> None:
        super().__init__(llm_client=None)
        self.bodies = bodies

    async def _run_reserved(self, **arguments: Any) -> Any:
        return await self.bodies[arguments["agent_id"]](arguments)


def _issued() -> TicketFinding:
    return TicketFinding(
        "issue", "ticket_issued", f"Ticket {RAW_ID} issued to {AGENT_A} for intent at intent, depth 0.",
        ticket_id=RAW_ID, principal_key=AGENT_A, work_kind="intent",
    )


def _live() -> TicketFinding:
    return TicketFinding(
        SEAM_TOOL, "ticket_live", f"Ticket {RAW_ID} of {AGENT_A} is live at tool.", ticket_id=RAW_ID,
        principal_key=AGENT_A, work_kind="intent",
    )


def _revoked() -> TicketFinding:
    return TicketFinding(
        SEAM_TOOL, "ticket_revoked",
        f"Ticket {RAW_ID} is revoked: its principal or an ancestor's is under the Captain's stop s.",
        ticket_id=RAW_ID, principal_key=AGENT_A, work_kind="agentic_run", stop_id="s",
    )


def _expired() -> TicketFinding:
    return TicketFinding(
        SEAM_TOOL, "ticket_expired", f"Ticket {RAW_ID} ended: it expired, or was released when its work ended.",
        ticket_id=RAW_ID, principal_key=AGENT_A, work_kind="agentic_run",
    )


def _missing() -> TicketFinding:
    return TicketFinding(SEAM_MODEL_CALL, "ticket_missing", "No ticket was presented at model_call.", presented_key=AGENT_A)


def _unknown() -> TicketFinding:
    return TicketFinding(SEAM_TOOL, "ticket_unknown", "The presented object is not a ticket the registry holds.")


async def _settle() -> None:
    """Let the loop run the checks a sink elsewhere handed to it."""
    for _ in range(3):
        await asyncio.sleep(0)


async def _until(check: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not await check():
        assert loop.time() < deadline, "the condition did not hold in time"
        await asyncio.sleep(0.01)


def _tools(stops: AgentStopService, service: AdmissionService) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    return registry


def _gateway(service: AdmissionService) -> _OfflineGateway:
    client = _OfflineGateway()
    client.set_admission(service)
    return client


async def _run(runner: _ScriptedRun, runtime: SimpleNamespace, agent_id: str, extra: dict[str, Any] | None = None) -> Any:
    """The real run entry: its stop check, shadow statement and hold, then the scripted body under the hold."""
    return await runner.run(agent_id=agent_id, instructions="i", task_text="t", runtime=runtime, extra_context=extra)


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = True
    return config


@pytest_asyncio.fixture
async def identities(tmp_path: Path) -> AsyncIterator[IdentityService]:
    """The real facade over a started identity registry and a ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        callsigns = CallsignRegistry()
        callsigns.bind_registry(AgentRegistry())
        yield IdentityService(registry, callsigns)
    finally:
        await registry.stop()


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[AdmissionShadowStore]:
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        yield shadow
    finally:
        await shadow.stop()


@pytest.fixture
def tickets(stops: AgentStopService) -> TicketRegistry:
    """A production-shaped registry at the default delegation depth of 1, on a clock that does not move."""
    return TicketRegistry(stops, max_depth=1, clock=lambda: 1_000.0)


async def test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO1 (kills OX-5, OX-7, OX-8, OX-9, OX-11, OX-14, OX-15, OX-18, OX-19, OX-20, OX-23, OX-40, OX-43, OX-44); then
    one finding of each code and of each work kind, with no room in the sample buffer."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    revoked, missing, unknown = _revoked(), _missing(), _unknown()
    recorder.offer_ticket(_issued(), off_loop=False)
    recorder.offer_ticket(_live(), off_loop=False)
    recorder.offer_ticket(revoked, off_loop=False)
    recorder.offer_ticket(missing, off_loop=True)
    recorder.offer_ticket(unknown, off_loop=False)
    await recorder.stop()
    assert await rows(store.path, FINDINGS) == [
        (DAY, "issue", "ticket_issued", "intent", 0, 1),
        (DAY, "model_call", "ticket_missing", "", 1, 1),
        (DAY, "tool", "ticket_live", "intent", 0, 1),
        (DAY, "tool", "ticket_revoked", "agentic_run", 0, 1),
        (DAY, "tool", "ticket_unknown", "", 0, 1),
    ]
    ring = "SELECT code, off_loop, recorded_at, finding_json FROM {} ORDER BY seq"
    kept = await rows(store.path, ring.format("ticket_samples"))
    assert [(code, off_loop, at, json.loads(text)) for code, off_loop, at, text in kept] == [
        ("ticket_revoked", 0, T0, persisted_finding(revoked)), ("ticket_unknown", 0, T0, persisted_finding(unknown)),
    ]
    held = await rows(store.path, ring.format("ticket_missing_samples"))
    assert [(code, off_loop, at, json.loads(text)) for code, off_loop, at, text in held] == [
        ("ticket_missing", 1, T0, persisted_finding(missing)),
    ]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 5, 5, 0, 0)]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {"ticket_offered": 5, "ticket_written": 5}
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 0)
    every = ShadowRecorder(store, wall_clock=_Clock(T0))  # never started: it holds no task and writes nothing
    for code in TICKET_REASON_CODES:
        every.offer_ticket(TicketFinding(SEAM_TOOL, code, "c"), off_loop=False)
    for work_kind in (*WORK_KINDS, ""):
        every.offer_ticket(TicketFinding(SEAM_TOOL, "ticket_live", "c", work_kind=work_kind), off_loop=False)
    assert every.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "ticket_offered": len(TICKET_REASON_CODES) + len(WORK_KINDS) + 1,
        "ticket_samples_dropped": len(TICKET_REASON_CODES) - 3,
    }, "every code but ticket_issued, ticket_live and ticket_missing offers a sample to the buffer of 0"


async def test_offer_ticket_refuses_a_finding_it_cannot_bound_and_keeps_nothing_of_it(store: AdmissionShadowStore) -> None:
    """TO2 (kills OX-2, OX-3, OX-4): register R53's checks, made before anything is counted."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    with pytest.raises(TypeError, match="TicketFinding"):
        recorder.offer_ticket(object(), off_loop=False)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bool"):
        recorder.offer_ticket(_missing(), off_loop=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TicketFinding"):
        recorder.offer_ticket(_SubFinding(SEAM_TOOL, "ticket_live", "c", work_kind="intent"), off_loop=False)
    with pytest.raises(ValueError, match="WORK_KINDS"):
        recorder.offer_ticket(TicketFinding(SEAM_TOOL, "ticket_live", "c", work_kind="not_a_work_kind"), off_loop=False)
    for subclassed in (
        TicketFinding(_Kind(SEAM_TOOL), "ticket_live", "c", work_kind="intent"),
        TicketFinding(SEAM_TOOL, _Kind("ticket_live"), "c", work_kind="intent"),
        TicketFinding(SEAM_TOOL, "ticket_live", "c", work_kind=_Kind("intent")),
    ):
        with pytest.raises(ValueError, match="WORK_KINDS"):
            recorder.offer_ticket(subclassed, off_loop=False)
    await recorder.stop()
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0)
    assert await rows(
        store.path,
        "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
        "(SELECT COUNT(*) FROM ticket_missing_samples), (SELECT COUNT(*) FROM ticket_markers)",
    ) == [(0, 0, 0, 0)]


def test_offer_ticket_awaits_nothing_and_calls_no_store_task_wait_or_io_name() -> None:
    """TO3: #1601's bottleneck rule on the hot path, as R2 holds ``offer`` to it."""
    node = function("src/probos/admission/recorder.py", "ShadowRecorder.offer_ticket")
    assert isinstance(node, ast.FunctionDef), "offer_ticket must not be a coroutine"
    forbidden = {
        "write_batch", "prune", "connect", "execute", "executemany", "commit", "create_task", "sleep", "wait",
        "wait_for", "open", "acquire", "dumps", "run_in_executor",
    }
    for child in ast.walk(node):
        assert not isinstance(child, (ast.Await, ast.AsyncFor, ast.AsyncWith)), child.lineno
        if isinstance(child, ast.Call):
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            assert name not in forbidden, (child.lineno, name)


async def test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO4 (kills OX-1, OX-6, OX-10, OX-12, OX-13, OX-16)."""
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 3)
    monkeypatch.setattr(recorder_module, "TICKET_MISSING_BUFFER_LIMIT", 1)
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 2)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    # keys: missing (1), revoked (2), unknown (3, its sample beyond the buffer of 2), expired (a fourth key: dropped)
    for finding in (_missing(), _missing(), _revoked(), _revoked(), _unknown(), _expired()):
        recorder.offer_ticket(finding, off_loop=False)
    await recorder.stop()
    recorder.offer_ticket(_revoked(), off_loop=False)
    await recorder.stop()
    assert await rows(store.path, FINDINGS) == [
        (DAY, "model_call", "ticket_missing", "", 0, 2),
        (DAY, "tool", "ticket_revoked", "agentic_run", 0, 2),
        (DAY, "tool", "ticket_unknown", "", 0, 1),
    ]
    assert await rows(store.path, "SELECT code FROM ticket_samples ORDER BY seq") == [("ticket_revoked",), ("ticket_revoked",)]
    assert await rows(store.path, "SELECT code FROM ticket_missing_samples ORDER BY seq") == [("ticket_missing",)]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 6, 5, 1, 2)]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "ticket_offered": 6, "ticket_written": 5, "ticket_dropped": 1, "ticket_samples_dropped": 2, "ticket_late": 1,
    }


async def test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written(
    store: AdmissionShadowStore, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO5 (kills OX-21, OX-22, OX-24, OX-25, OX-26, OX-37, OX-38, OX-39, OX-50, OX-51, OX-52): D150, first with a
    cause the store meets, on a part that also holds two dropped keys, a sample dropped at its offer and a
    ``ticket_missing`` sample; then with a cause that clears before the second write, on a part of counts only (register
    R59), and on a part whose two samples, one in each buffer, fall in two hours that held no dropped count."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.recorder")
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 3)
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 1)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    poisoned = TicketFinding(SEAM_TOOL, "ticket_unknown", "c", ticket_id=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        persisted_finding(poisoned)  # premise: the ring row of this sample cannot be built
    recorder.offer(refuse(), 1)
    # keys: issued (1), unknown (2: the poisoned sample kept, the next unknown's beyond the buffer of 1) and missing
    # (3, its sample in the missing buffer); expired and live need a fourth and a fifth key: dropped (two, against the
    # one sample dropped at its offer)
    for finding in (_issued(), poisoned, _unknown(), _missing(), _expired(), _live()):
        recorder.offer_ticket(finding, off_loop=False)
    await recorder.stop()
    assert await rows(store.path, "SELECT outcome, decisions FROM shadow_aggregates") == [("would_refuse", 1)]
    assert await rows(store.path, "SELECT SUM(offered), SUM(written) FROM shadow_markers") == [(1, 1)]
    assert await rows(
        store.path,
        "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
        "(SELECT COUNT(*) FROM ticket_missing_samples)",
    ) == [(0, 0, 0)]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 6, 0, 6, 3)]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "offered": 1, "written": 1, "flush_failures": 1, "ticket_offered": 6, "ticket_dropped": 6,
        "ticket_samples_dropped": 3,
    }
    records = [r for r in caplog.records if r.name == "probos.admission.recorder"]
    assert [r.levelno for r in records] == [logging.WARNING]
    shadow = _FailingStore(data_dir=tmp_path / "transient", failures=1)
    await shadow.start()
    try:
        transient = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        transient.offer_ticket(_issued(), off_loop=False)
        await transient.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 2
    assert await rows(shadow.path, "SELECT COUNT(*) FROM ticket_findings") == [(0,)]
    assert await rows(shadow.path, MARKERS) == [(transient.boot_id, utc_hour(T0), 1, 0, 1, 0)]
    assert transient.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "flush_failures": 1, "ticket_offered": 1, "ticket_dropped": 1,
    }
    rewritten_store = _FailingStore(data_dir=tmp_path / "rewritten", failures=1)
    await rewritten_store.start()
    try:
        clock = _Clock(T0)
        rewritten = ShadowRecorder(rewritten_store, wall_clock=clock)
        rewritten.offer_ticket(_revoked(), off_loop=False)
        clock.now = T0 + HOUR
        rewritten.offer_ticket(_missing(), off_loop=False)
        await rewritten.stop()
    finally:
        await rewritten_store.stop()
    assert rewritten_store.attempts == 2
    assert await rows(
        rewritten_store.path,
        "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
        "(SELECT COUNT(*) FROM ticket_missing_samples)",
    ) == [(0, 0, 0)]
    assert await rows(rewritten_store.path, MARKERS) == [
        (rewritten.boot_id, utc_hour(T0), 1, 0, 1, 1), (rewritten.boot_id, utc_hour(T0 + HOUR), 1, 0, 1, 1),
    ], "each rewritten sample adds one in its own hour, which held no dropped count"
    assert rewritten.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "flush_failures": 1, "ticket_offered": 2, "ticket_dropped": 2, "ticket_samples_dropped": 2,
    }


async def test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO6 (kills OX-27 to OX-36): the batch of the first flush, with two dropped keys and a dropped sample, fails
    twice; offers made in the next hour while its first write is in flight overflow both buffers, by two and by one,
    when it is put back, and the batch's own samples are the ones kept."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 2)
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 2)
    monkeypatch.setattr(recorder_module, "TICKET_MISSING_BUFFER_LIMIT", 1)
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=2)
    await shadow.start()
    try:
        clock = _Clock(T0)
        recorder = ShadowRecorder(shadow, wall_clock=clock)

        other_missing = TicketFinding(
            SEAM_MODEL_CALL, "ticket_missing", "No ticket was presented at model_call.", presented_key=AGENT_B,
        )

        def during() -> None:  # next hour: two samples of a new key, and a missing sample told apart from the batch's
            clock.now = T0 + HOUR
            recorder.offer_ticket(_expired(), off_loop=False)
            recorder.offer_ticket(_expired(), off_loop=False)
            recorder.offer_ticket(other_missing, off_loop=False)

        shadow.during = during
        recorder.start()
        # three revoked (the third beyond the sample buffer), one missing, one unknown and one live (a third and a
        # fourth key: dropped)
        for finding in (_revoked(), _revoked(), _revoked(), _missing(), _unknown(), _live()):
            recorder.offer_ticket(finding, off_loop=False)

        async def written_after_the_failures() -> bool:
            return shadow.attempts >= 3

        await _until(written_after_the_failures)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 3
    assert await rows(shadow.path, FINDINGS) == [
        (DAY, "model_call", "ticket_missing", "", 0, 2), (DAY, "tool", "ticket_expired", "agentic_run", 0, 2),
        (DAY, "tool", "ticket_revoked", "agentic_run", 0, 3),
    ]
    assert await rows(shadow.path, "SELECT code FROM ticket_samples ORDER BY seq") == [("ticket_revoked",)] * 2
    held = await rows(shadow.path, "SELECT finding_json FROM ticket_missing_samples")
    assert [json.loads(text) for (text,) in held] == [persisted_finding(_missing())]
    assert await rows(shadow.path, MARKERS) == [
        (recorder.boot_id, utc_hour(T0), 6, 4, 2, 1), (recorder.boot_id, utc_hour(T0 + HOUR), 3, 3, 0, 3),
    ]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "flush_failures": 2, "ticket_offered": 9, "ticket_written": 7, "ticket_dropped": 2, "ticket_samples_dropped": 4,
    }


async def test_stop_logs_each_failed_write_and_the_counts_it_could_not_write(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """TO7 (kills OX-41, OX-42): two flushes of two writes each, every one of them raising; each batch they put back is
    within both work-ticket buffers."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.recorder")
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=10)
    await shadow.start()
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        recorder.offer(refuse(), 1)
        recorder.offer(admit(), 1)
        # four findings under three keys, and three samples in two buffers: the warning's four counts differ
        for finding in (_missing(), _missing(), _unknown(), _issued()):
            recorder.offer_ticket(finding, off_loop=False)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 4
    records = [r for r in caplog.records if r.name == "probos.admission.recorder"]
    assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG, logging.DEBUG, logging.DEBUG, logging.WARNING]
    assert records[-1].args == (2, 1, 4, 3)
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "offered": 2, "flush_failures": 4, "ticket_offered": 4,
    }, "each put-back batch is within both buffers: nothing is counted as dropped"
    assert await rows(shadow.path, "SELECT COUNT(*) FROM ticket_markers") == [(0,)]


async def test_the_service_offers_each_issue_and_sink_finding_on_the_thread_of_its_check(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, store: AdmissionShadowStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO8 (kills OX-48, OX-49): D152's two offer points; the model call is checked on a worker thread and handed to the
    service's loop."""
    recorder = _ThreadRecordingRecorder(store, wall_clock=_Clock(T0))
    service = AdmissionService(identities, stops, recorder=recorder, tickets=tickets, loop=asyncio.get_running_loop())
    hold = service.hold(presented_id=AGENT_A, work_kind="intent", seam=SEAM_INTENT, child=False)
    try:
        assert CURRENT_TICKET.get() is not None, "premise: the hold carried its ticket"
        service.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A)
        await asyncio.to_thread(service.check_ticket, effect=SEAM_MODEL_CALL, presented_id=None)
        await _settle()
    finally:
        hold.end()
    monkeypatch.setattr(tickets_module, "MAX_TICKETS", 0)
    service.hold(presented_id=AGENT_A, work_kind="intent", seam=SEAM_INTENT, child=False).end()
    await recorder.stop()
    assert await rows(store.path, FINDINGS) == [
        (DAY, "issue", "ticket_issued", "intent", 0, 1),
        (DAY, "issue", "ticket_registry_full", "intent", 0, 1),
        (DAY, "model_call", "ticket_live", "intent", 1, 1),
        (DAY, "tool", "ticket_live", "intent", 0, 1),
    ]
    assert await rows(store.path, "SELECT operation, code FROM ticket_samples") == [("issue", "ticket_registry_full")]
    assert recorder.threads == [threading.get_ident()] * 4, "each offer ran on the loop's thread"
    assert service.off_loop_checks() == {SEAM_MODEL_CALL: 1} and service.failures == 0


async def test_an_offer_that_raises_is_one_counted_failure_and_hold_leaves_the_carrier_as_it_was(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, store: AdmissionShadowStore,
) -> None:
    """TO9: #1604 property 6 for the offers; an offer that raises a ``RuntimeError`` counts one failure, in ``hold`` it
    runs before the carrier is set, and in ``_check_ticket`` after the off-loop count."""
    plain = AdmissionService(identities, stops, tickets=tickets)
    service = AdmissionService(
        identities, stops, recorder=_RaisingTicketRecorder(store), tickets=tickets, loop=asyncio.get_running_loop(),
    )
    outer = plain.hold(presented_id=AGENT_A, work_kind="intent", seam=SEAM_INTENT, child=False)
    try:
        assert outer.ticket is not None and CURRENT_TICKET.get() is outer.ticket, "premise: the outer hold is carried"
        assert service.hold(presented_id=AGENT_B, work_kind="intent", seam=SEAM_INTENT, child=False) is NO_HOLD
        assert CURRENT_TICKET.get() is outer.ticket, "the carrier is as it was"
        assert service.failures == 1 and len(tickets) == 2, "one failure; the issued entry stays registered"
        service.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A)
        assert service.failures == 2
        await asyncio.to_thread(service.check_ticket, effect=SEAM_MODEL_CALL, presented_id=None)
        await _settle()
        assert service.failures == 3 and service.off_loop_checks() == {SEAM_MODEL_CALL: 1}, (
            "the handed-over check was counted off the loop before its offer raised"
        )
    finally:
        outer.end()
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 2, ("tool", "ticket_live"): 1, ("model_call", "ticket_live"): 1,
    }


async def test_a_captains_stop_reaches_a_run_and_its_delegated_child_in_the_persisted_record(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, store: AdmissionShadowStore,
) -> None:
    """TO10: the chain of register R52, from the sinks of a real run entry to the report's queries (#1604 properties 5
    and 8)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    service = AdmissionService(identities, stops, recorder=recorder, tickets=tickets, loop=asyncio.get_running_loop())
    tools = _tools(stops, service)
    gateway = _gateway(service)
    runtime = SimpleNamespace(tool_registry=tools, admission_service=service)
    seen: dict[str, Any] = {}

    async def model_and_tool(agent_id: str) -> None:
        await gateway.complete(LLMRequest(prompt="p", agent_id=agent_id))
        await tools.check_and_invoke(agent_id, _ABSENT, {})

    async def parent(arguments: dict[str, Any]) -> str:
        seen["parent"] = CURRENT_TICKET.get()
        await model_and_tool(AGENT_A)
        result = await _run(runner, runtime, AGENT_B, {"_delegation_depth": 1})
        await model_and_tool(AGENT_A)
        return result

    async def child(arguments: dict[str, Any]) -> str:
        seen["child"] = CURRENT_TICKET.get()
        await model_and_tool(AGENT_B)
        issued = await stops.issue_stop(AGENT_A, reason="ad1346-m3d3b2: the Captain stops the delegating agent")
        seen["stop_id"] = issued.record.stop_id
        await model_and_tool(AGENT_B)
        return "child ran"

    runner = _ScriptedRun({AGENT_A: parent, AGENT_B: child})
    assert await _run(runner, runtime, AGENT_A) == "child ran"
    assert seen["parent"] is not None and seen["child"] is not None, "premise: both runs held a ticket"
    parent_id, child_id = seen["parent"].ticket_id, seen["child"].ticket_id
    assert service.failures == 0
    await recorder.stop()
    db = await open_read_only(store.path)
    try:
        by_operation = await run_query(db, "ticket_findings_by_operation", (DAY,))
        samples = await run_query(db, "ticket_samples", (10,))
        missing = await run_query(db, "ticket_missing_samples", (10,))
        markers = await run_query(db, "ticket_markers_by_boot")
    finally:
        await db.close()
    assert by_operation == [
        ("issue", "ticket_issued", "agentic_run", 0, 2),
        ("model_call", "ticket_live", "agentic_run", 0, 2),
        ("model_call", "ticket_revoked", "agentic_run", 0, 2),
        ("tool", "ticket_live", "agentic_run", 0, 2),
        ("tool", "ticket_revoked", "agentic_run", 0, 2),
    ]
    assert [(row[3], row[4]) for row in samples] == [("tool", "ticket_revoked"), ("model_call", "ticket_revoked")] * 2
    bodies = [json.loads(row[7]) for row in samples]
    assert [(body["ticket_id"], body["parent_id"], body["depth"]) for body in bodies] == [
        (ticket_digest(parent_id), "", 0), (ticket_digest(parent_id), "", 0),
        (ticket_digest(child_id), ticket_digest(parent_id), 1), (ticket_digest(child_id), ticket_digest(parent_id), 1),
    ], "newest first: the delegating run's two calls after the child returned, then the child's two"
    assert all(body["stop_id"] == seen["stop_id"] for body in bodies)
    assert not any(parent_id in row[7] or child_id in row[7] for row in samples), "no raw ticket id in a ring row"
    assert missing == []
    assert markers == [(recorder.boot_id, utc_hour(T0), utc_hour(T0), 10, 10, 0, 0)]


async def test_a_boot_persists_a_model_calls_finding_after_the_runtime_stops(tmp_path: Path) -> None:
    """TO11: the wiring of the record, on one boot."""
    runtime = ProbOSRuntime(config=_config(), data_dir=tmp_path / "boot", llm_client=_OfflineGateway())
    await runtime.start()
    try:
        recorder = runtime.admission_shadow_recorder
        assert isinstance(recorder, ShadowRecorder) and isinstance(runtime.llm_client, _OfflineGateway), (
            "premise: the boot built the recorder and kept the gateway"
        )
        boot_id = recorder.boot_id
        await runtime.llm_client.complete(LLMRequest(prompt="ad1346-m3d3b2"))
    finally:
        await runtime.stop()
    db = await open_read_only(tmp_path / "boot" / STORE_FILENAME)
    try:
        by_operation = await run_query(db, "ticket_findings_by_operation", ("1970-01-01",))
        markers = await run_query(db, "ticket_markers_by_boot")
    finally:
        await db.close()
    assert any(row[:3] == ("model_call", "ticket_missing", "") and row[4] >= 1 for row in by_operation), by_operation
    mine = [row for row in markers if row[0] == boot_id]
    assert len(mine) == 1 and mine[0][3] == mine[0][4] >= 1 and mine[0][5] == 0, mine


async def test_the_counters_append_five_ticket_totals_and_start_marks_the_ticket_hour(store: AdmissionShadowStore) -> None:
    """TO12 (kills OX-17, OX-45, OX-46, OX-47)."""
    assert COUNTER_NAMES[8:] == (
        "ticket_offered", "ticket_written", "ticket_dropped", "ticket_samples_dropped", "ticket_late",
    )
    assert recorder_module.TICKET_SAMPLE_BUFFER_LIMIT == TICKET_SAMPLE_RING_SIZE
    assert recorder_module.TICKET_MISSING_BUFFER_LIMIT == TICKET_MISSING_RING_SIZE
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.start()
    await recorder.stop()
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 0, 0, 0, 0)]
```

### 7.6 M2: `tests/test_ad1346_admission_ticket_record.py` (M3d3b1's new file)

**M2-01** (module docstring)

SEARCH:
```
UTC hour); ``prune`` bounds the counts and the markers. In ``src`` the recorder, the one caller of ``write_batch``,
builds each batch without a work-ticket part, so that part is the empty default until AD-1346 M3d3b2 adds the
recorder's offers. The tests that write the part build it directly, with findings from a real ``TicketRegistry``
```
REPLACE:
```
UTC hour); ``prune`` bounds the counts and the markers. In ``src`` the recorder, the one caller of ``write_batch``,
fills that part from its offers from AD-1346 M3d3b2 (``tests/test_ad1346_admission_ticket_offers.py``). The tests
here that write the part build it directly, with findings from a real ``TicketRegistry``
```

## 8. Tracking (M3's commit)

**Date rule.** If M3 is committed on a date other than 2026-10-30, the Builder substitutes the commit date for `2026-10-30` in exactly two strings, both new:
- the new paragraph's head `**AD-1346 (2026-10-30), #1604 M3d3b2 -- ` in M3-01's REPLACE;
- the new heading `### AD-1346 M3d3b2 -- the recorder's offers: work-ticket findings written to admission_shadow.db (2026-10-30, #1604)` in M3-02's REPLACE.

M3-01's SEARCH text and the M3d3b1 head its REPLACE keeps must be M3d3b1's head as merged. If M3d3b1's own date rule gave it another date, use that date in both. The commit date is the committing machine's local date when M3 is committed, not the UTC date. No other deviation is permitted.

Then regenerate the ledger with `python -P scripts/gen_ad_ledger.py` (write mode), and commit `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. Two bullets for `DECISIONS.md` are added in a later docs commit, after the reviewed commit: the campaign of record, and D156's measured figures.

**Where the entries land.**
- M3-01 puts the new paragraph between the title line `# ProbOS Progress` and M3d3b1's paragraph (`PROGRESS.md:3` on `35045636`). `PROGRESS.md` runs newest first.
- M3-02 puts M3d3b2's entry (its heading, paragraph and bullets, the last of them its `*Reversal.*` bullet, then a blank line) directly above `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)` (`DECISIONS.md:1051` on `35045636`). That is the heading that follows M3d3b1's entry (`:1036`), so the AD-1346 entries run oldest first. M3d3b1's later docs bullets go inside its own entry, above that heading, so this anchor holds.
- Neither new head carries a status keyword of `scripts/gen_ad_ledger.py:126-132` in its first 120 characters (`:139`).

**M3-01** (`PROGRESS.md`)

SEARCH:
```
# ProbOS Progress

**AD-1346 (2026-10-30), #1604 M3d3b1 -- 
```
REPLACE:
```
# ProbOS Progress

**AD-1346 (2026-10-30), #1604 M3d3b2 -- the recorder's offers: the work-ticket findings of an issue and of a sink check, written to `admission_shadow.db`.** `ShadowRecorder.offer_ticket` checks a `TicketFinding` (its type, an exact `bool` `off_loop`, exact-`str` key parts and a work kind in `WORK_KINDS` or empty), counts it by hour, operation, code, work kind and `off_loop`, and keeps a sample of every code but `ticket_issued` and `ticket_live`, `ticket_missing` in a buffer of its own; each flush writes that part in the transaction of the verdicts. `AdmissionService.hold` offers the issue's finding before it sets the carrier, and `_check_ticket` the sink check's after its off-loop count. `COUNTER_NAMES` appends five `ticket_` totals, `start` marks the boot's hour in the work-ticket markers, and `stop`'s warning counts the work-ticket findings and samples it could not write. A new test file drives a Captain's stop through the real run entry and its delegated child to the report's `ticket_` queries, and a boot's model call to the store after `runtime.stop()`. The contract is `prompts/ad-1346-m3d3b2-ticket-offers.md`.

**AD-1346 (2026-10-30), #1604 M3d3b1 -- 
```

**M3-02** (`DECISIONS.md`)

SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1346 M3d3b2 -- the recorder's offers: work-ticket findings written to admission_shadow.db (2026-10-30, #1604)

AD-1346 M3d3b2 fills the work ticket's persisted record that M3d3b1 built: the shadow recorder takes the findings the ticket registry answers at an issue (`hold`) and at a sink check (`_check_ticket`) and writes them behind, in the flush transaction of the verdicts. It delivers #1604 property 8's service-written record and markers for the work ticket, and the persisted evidence of properties 3 and 5 and of registers R37 to R39 and R49. The contract is `prompts/ad-1346-m3d3b2-ticket-offers.md`.

- *D150 (a failing part).* When a write raises an `Exception` and its work-ticket part holds a finding count or a sample, the flush writes the batch again at once with each of them counted as dropped in the work-ticket markers, so a finding or sample cannot keep the verdicts from that second write; when it raises too, the batch is put back whole. Rejected: checks in the offer that would have to cover everything the store can raise, a separate transaction for the work-ticket part (which would reverse D140), and never putting a failed work-ticket part back.
- *D151 (the offer).* `offer_ticket(finding, *, off_loop)` refuses with `TypeError` or `ValueError` what the store's bound cannot hold (register R53); it counts every accepted finding, samples none of `ticket_issued` and `ticket_live`, and keeps `ticket_missing` samples apart, with the verdicts' bounds and the ring sizes as buffers.
- *D152 (the offer points).* In `hold` before the carrier is set, so a raising offer leaves it as it was; in `_check_ticket` after the off-loop count; each on the thread of the registry call it reports. Rejected: a registry hook, and offers from the seam helpers, which receive no finding.
- *D153 (markers and the crash window).* Per boot and hour, offered equals written plus dropped once committed; `start` marks a work-ticket marker row. A crash loses the pending counts with their markers; the property 8 report is to count the boots whose end AD-820 did not mark clean, with a bound of the flush interval and any failed writes. Rejected: a clean-stop row (a schema change) and writing the offered count ahead of its counts.
- *D158 (the clock).* From this deploy, a fix that changes which findings are kept, or under which key, restarts the 7 days for the sink records; a fix to the markers, the start mark, the stop warning, the counters, a report query or the digest does not.
- *Tests.* One new file (`tests/test_ad1346_admission_ticket_offers.py`, TO1 to TO12); P13 now pins M3c's two counter names by position, T14's `recorder.py` allowlist gains `dataclasses` and `probos.admission.tickets`, and the record test's docstring names the recorder as the part's producer.
- *Residual, accepted.* Register R58 to R64 of the contract.
- *Reversal.* Revert the M3d3b2 commits. The recorder then builds each batch without a work-ticket part again; rows a vessel already wrote stay in the four tables, which M3d3b1's `prune` and ring trims bound.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

## 9. What this does NOT change

- `store.py`, `report.py`, `storage_declarations.py`, `tickets.py`, `carrier.py`, `seam.py`, `taxonomy.py`, `record.py`; the schema, `SCHEMA_VERSION`, every table and statement; `write_batch`'s and `prune`'s return values; `TICKET_FINDING_KEYS`.
- `offer`, its bounds and its counters; `shadow`, `decide`, `check_ticket`'s hand-off, `close`, `off_loop_checks`, `failures`'s meaning, `AdmissionService`'s constructor and attributes.
- `runtime.py`, `startup/*` (the shutdown order), `config.py`, `config/system.yaml`, every sink and entry, every `shadow_at`, `hold_at` and `check_at` call.
- The behaviour of a write that raises for a batch whose work-ticket part holds no finding count and no sample: it is put back whole, as before.
- `docs/development/store-baseline.yaml`, `docs/development/architecture-baseline.yaml`, `tests/fixtures/ad1343_seam_census.py`.

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline passes; run on the Captain's Windows host)

Group and its `--tests`: every OX row runs against `tests/test_ad1346_admission_ticket_offers.py`. No two rows mutate the same line. Each Line is a stripped line that occurs once in its file at M1's tree and at M2's tree (Builder: confirm with `grep -c` before the campaign; a line found twice is a hard stop for the Architect). No row is expected to be equivalent.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| OX-1 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_late"] += 1` | `pass` | `test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory` |
| OX-2 | M1 | `src/probos/admission/recorder.py` | `if type(finding) is not TicketFinding or type(off_loop) is not bool:` | `if False:` | `test_offer_ticket_refuses_a_finding_it_cannot_bound_and_keeps_nothing_of_it` |
| OX-3 | M1 | `src/probos/admission/recorder.py` | `if not exact or work_kind not in _OFFERED_WORK_KINDS:` | `if not exact:` | `test_offer_ticket_refuses_a_finding_it_cannot_bound_and_keeps_nothing_of_it` |
| OX-4 | M1 | `src/probos/admission/recorder.py` | `exact = type(operation) is str and type(code) is str and type(work_kind) is str` | `exact = True` | `test_offer_ticket_refuses_a_finding_it_cannot_bound_and_keeps_nothing_of_it` |
| OX-5 | M1 | `src/probos/admission/recorder.py` | `key = (hour, operation, code, work_kind, off_loop)` | `key = (hour, operation, code, work_kind, False)` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-6 | M1 | `src/probos/admission/recorder.py` | `elif len(self._ticket_findings) < PENDING_KEY_LIMIT:` | `elif True:` | `test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory` |
| OX-7 | M1 | `src/probos/admission/recorder.py` | `if code in _COUNTED_ONLY:` | `if False:` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-8 | M1 | `src/probos/admission/recorder.py` | `missing = code == TICKET_MISSING` | `missing = False` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-9 | M1 | `src/probos/admission/recorder.py` | `buffer = self._ticket_missing if missing else self._ticket_samples` | `buffer = self._ticket_samples if missing else self._ticket_missing` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-10 | M1 | `src/probos/admission/recorder.py` | `if len(buffer) < (TICKET_MISSING_BUFFER_LIMIT if missing else TICKET_SAMPLE_BUFFER_LIMIT):` | `if len(buffer) < (TICKET_SAMPLE_BUFFER_LIMIT if missing else TICKET_MISSING_BUFFER_LIMIT):` | `test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory` |
| OX-11 | M1 | `src/probos/admission/recorder.py` | `buffer.append(TicketSample(hour, now, finding, off_loop))` | `pass` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-12 | M1 | `src/probos/admission/recorder.py` | `self._ticket_samples_dropped[hour] = self._ticket_samples_dropped.get(hour, 0) + 1` | `pass` | `test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory` |
| OX-13 | M1 | `src/probos/admission/recorder.py` | `self._ticket_dropped[hour] = self._ticket_dropped.get(hour, 0) + 1` | `pass` | `test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory` |
| OX-14 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_offered"] += 1` | `pass` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-15 | M1 | `src/probos/admission/recorder.py` | `self._ticket_offered[hour] = self._ticket_offered.get(hour, 0) + 1` | `pass` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-16 | M1 | `src/probos/admission/recorder.py` | `self._ticket_findings[key] += 1` | `pass` | `test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory` |
| OX-17 | M1 | `src/probos/admission/recorder.py` | `self._ticket_offered.setdefault(hour, 0)  # AD-1346 M3d3b2 (D153): the boot's work-ticket marker row too` | `pass` | `test_the_counters_append_five_ticket_totals_and_start_marks_the_ticket_hour` |
| OX-18 | M1 | `src/probos/admission/recorder.py` | `parity=self._parity, disagreements=self._disagreements, tickets=tickets,` | `parity=self._parity, disagreements=self._disagreements,` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-19 | M1 | `src/probos/admission/recorder.py` | `self._ticket_findings, self._ticket_samples, self._ticket_missing = {}, [], []` | `pass` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-20 | M1 | `src/probos/admission/recorder.py` | `self._ticket_offered, self._ticket_dropped, self._ticket_samples_dropped = {}, {}, {}` | `pass` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-21 | M1 | `src/probos/admission/recorder.py` | `if isinstance(exc, Exception) and (tickets.findings or tickets.samples or tickets.missing):` | `if False:` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-22 | M1 | `src/probos/admission/recorder.py` | `await self._write_without_ticket_rows(batch)  # D150: written without its ticket rows, or put back whole` | `self._restore(batch)` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-23 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_written"] += sum(tickets.findings.values())` | `pass` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-24 | M1 | `src/probos/admission/recorder.py` | `written = await self._store.write_batch(self._boot_id, replace(batch, tickets=_as_dropped(tickets)))` | `written = await self._store.write_batch(self._boot_id, replace(batch, tickets=TicketBatch()))` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-25 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_dropped"] += sum(tickets.findings.values())` | `pass` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-26 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_samples_dropped"] += len(tickets.samples) + len(tickets.missing)` | `pass` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-27 | M1 | `src/probos/admission/recorder.py` | `_add(self._ticket_findings, tickets.findings)` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-28 | M1 | `src/probos/admission/recorder.py` | `_add(self._ticket_offered, tickets.offered)` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-29 | M1 | `src/probos/admission/recorder.py` | `_add(self._ticket_dropped, tickets.dropped)` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-30 | M1 | `src/probos/admission/recorder.py` | `_add(self._ticket_samples_dropped, tickets.samples_dropped)` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-31 | M1 | `src/probos/admission/recorder.py` | `samples, missing = tickets.samples + self._ticket_samples, tickets.missing + self._ticket_missing` | `samples, missing = tickets.samples, tickets.missing` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-32 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_samples_dropped"] += max(0, len(samples) - TICKET_SAMPLE_BUFFER_LIMIT)` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-33 | M1 | `src/probos/admission/recorder.py` | `self._totals["ticket_samples_dropped"] += max(0, len(missing) - TICKET_MISSING_BUFFER_LIMIT)` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-34 | M1 | `src/probos/admission/recorder.py` | `self._ticket_samples = _first(samples, TICKET_SAMPLE_BUFFER_LIMIT, self._ticket_samples_dropped)` | `self._ticket_samples = samples` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-35 | M1 | `src/probos/admission/recorder.py` | `self._ticket_missing = _first(missing, TICKET_MISSING_BUFFER_LIMIT, self._ticket_samples_dropped)` | `self._ticket_missing = missing` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-36 | M1 | `src/probos/admission/recorder.py` | `dropped[sample.hour] = dropped.get(sample.hour, 0) + 1` | `pass` | `test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers` |
| OX-37 | M1 | `src/probos/admission/recorder.py` | `dropped[hour] = dropped.get(hour, 0) + count` | `pass` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-38 | M1 | `src/probos/admission/recorder.py` | `samples_dropped[sample.hour] = samples_dropped.get(sample.hour, 0) + 1` | `pass` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-39 | M1 | `src/probos/admission/recorder.py` | `return TicketBatch(offered=dict(tickets.offered), dropped=dropped, samples_dropped=samples_dropped)` | `return TicketBatch(dropped=dropped, samples_dropped=samples_dropped)` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-40 | M1 | `src/probos/admission/recorder.py` | `or self._ticket_findings or self._ticket_samples or self._ticket_missing or self._ticket_offered` | `or False` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-41 | M1 | `src/probos/admission/recorder.py` | `sum(self._aggregates.values()), len(self._samples), sum(self._ticket_findings.values()),` | `sum(self._aggregates.values()), len(self._samples), 0,` | `test_stop_logs_each_failed_write_and_the_counts_it_could_not_write` |
| OX-42 | M1 | `src/probos/admission/recorder.py` | `len(self._ticket_samples) + len(self._ticket_missing),` | `len(self._ticket_samples),` | `test_stop_logs_each_failed_write_and_the_counts_it_could_not_write` |
| OX-43 | M1 | `src/probos/admission/recorder.py` | `_OFFERED_WORK_KINDS: Final = frozenset((*WORK_KINDS, ""))` | `_OFFERED_WORK_KINDS: Final = frozenset(WORK_KINDS)` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-44 | M1 | `src/probos/admission/recorder.py` | `_COUNTED_ONLY: Final = frozenset({TICKET_ISSUED, TICKET_LIVE})` | `_COUNTED_ONLY: Final = frozenset({TICKET_ISSUED})` | `test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings` |
| OX-45 | M1 | `src/probos/admission/recorder.py` | `"flush_errors", "ticket_offered", "ticket_written", "ticket_dropped", "ticket_samples_dropped", "ticket_late",` | `"flush_errors", "ticket_offered", "ticket_written", "ticket_dropped", "ticket_samples_dropped",` | `test_the_counters_append_five_ticket_totals_and_start_marks_the_ticket_hour` |
| OX-46 | M1 | `src/probos/admission/recorder.py` | `TICKET_SAMPLE_BUFFER_LIMIT: Final = TICKET_SAMPLE_RING_SIZE` | `TICKET_SAMPLE_BUFFER_LIMIT: Final = 1` | `test_the_counters_append_five_ticket_totals_and_start_marks_the_ticket_hour` |
| OX-47 | M1 | `src/probos/admission/recorder.py` | `TICKET_MISSING_BUFFER_LIMIT: Final = TICKET_MISSING_RING_SIZE` | `TICKET_MISSING_BUFFER_LIMIT: Final = 1` | `test_the_counters_append_five_ticket_totals_and_start_marks_the_ticket_hour` |
| OX-48 | M1 | `src/probos/admission/service.py` | `self._recorder.offer_ticket(issued.finding, off_loop=False)` | `pass` | `test_the_service_offers_each_issue_and_sink_finding_on_the_thread_of_its_check` |
| OX-49 | M1 | `src/probos/admission/service.py` | `self._recorder.offer_ticket(finding, off_loop=off_loop)` | `self._recorder.offer_ticket(finding, off_loop=False)` | `test_the_service_offers_each_issue_and_sink_finding_on_the_thread_of_its_check` |
| OX-50 | M1 | `src/probos/admission/recorder.py` | `dropped = dict(tickets.dropped)` | `dropped = {}` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-51 | M1 | `src/probos/admission/recorder.py` | `samples_dropped = dict(tickets.samples_dropped)` | `samples_dropped = {}` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |
| OX-52 | M1 | `src/probos/admission/recorder.py` | `for sample in tickets.samples + tickets.missing:` | `for sample in tickets.samples:` | `test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written` |

How the rows are killed (each TO<n> is the case whose test function the row's Killed-by cell names):
- **OX-1:** TO4's `ticket_late` is 0.
- **OX-2:** TO2's `object()` raises `AttributeError`, and its `off_loop=1` is counted.
- **OX-3:** TO2's unknown work kind is counted.
- **OX-4:** TO2's `str` subclass work kind is in the set and is counted.
- **OX-5:** TO1's `ticket_missing` row has `off_loop` 0.
- **OX-6:** TO4's fourth key is counted and nothing is dropped.
- **OX-7:** TO1's `ticket_samples` holds the issued and live findings.
- **OX-8, OX-9:** TO1's `ticket_missing` sample is in the wrong ring.
- **OX-10:** TO4 keeps two missing samples and one other.
- **OX-11:** TO1's rings are empty.
- **OX-12, OX-13:** TO4's marker row shows 0 samples dropped, or 0 dropped.
- **OX-14:** TO1's `ticket_offered` total is 0.
- **OX-15:** TO1's marker row has offered 0.
- **OX-16:** TO4's repeated keys count 1.
- **OX-17:** TO12 has no work-ticket marker row.
- **OX-18:** TO1's tables are empty.
- **OX-19, OX-20:** TO1's second stop flush writes the same counts or markers again.
- **OX-21, OX-22, OX-24:** TO5's verdicts are never written, or its work-ticket markers are missing.
- **OX-23:** TO1's `ticket_written` total is 0.
- **OX-25, OX-26:** TO5's `ticket_dropped` or `ticket_samples_dropped` total holds only what its offers dropped (2 and 1).
- **OX-27 to OX-30:** TO6's findings, offered, dropped or samples-dropped counts are missing after the restore.
- **OX-31 to OX-36:** TO6's rings exceed their buffers, or its overflow is not counted in the totals or the markers.
- **OX-37 to OX-39:** TO5's marker row lacks its dropped, samples-dropped or offered count.
- **OX-40:** TO1's ticket-only recorder writes nothing at stop.
- **OX-41, OX-42:** TO7's `record.args` differ.
- **OX-43:** TO1's empty work kind raises `ValueError`.
- **OX-44:** TO1's live finding is sampled.
- **OX-45:** TO12's names differ, and `ticket_late` raises `KeyError` where it is counted.
- **OX-46, OX-47:** TO12's limits differ from the ring sizes.
- **OX-48:** TO8 has no issue rows.
- **OX-49:** TO8's handed-over `model_call` row has `off_loop` 0.
- **OX-50, OX-51:** TO5's first marker row lacks the keys or the sample its offers dropped (dropped 4, or samples dropped 2).
- **OX-52:** TO5's marker row lacks its `ticket_missing` sample (samples dropped 2).

**Pinned with no row** (lines that occur more than once, or are not one-line mutants):
- `_first`'s `return samples[:limit]`: TO6's ring counts;
- hold's offer coming before `CURRENT_TICKET.set`: TO9;
- each offer's thread: TO8;
- (A1) other mutants of lines that have a row:
  - OX-4's line without its `type(operation) is str` or its `type(code) is str` conjunct: TO2's operation and code cases;
  - OX-11's line with a constant in place of `now`: TO1's `recorded_at`;
  - OX-21's line without `tickets.findings`: TO5's part of counts only, whose second write commits;
  - OX-26's line without `+ len(tickets.missing)`: TO5's `ticket_missing` sample;
  - OX-31's line with each sum's operands swapped (pending samples first): TO6's kept codes and kept missing finding;
  - OX-41's line with `len(self._ticket_findings)` for the sum, and OX-42's line without its first summand: TO7's `(2, 1, 4, 3)`;
- (A1) `_write_without_ticket_rows`'s `self._totals["written"] += written` (the line occurs twice): TO5's `written` total;
- (A1) `_check_ticket`'s offer coming after the off-loop count (a moved statement): TO9's `off_loop_checks`.
- (A2) other mutants of lines that have a row, from the orchestrator's one-line sweep or A2's closed sweep:
  - OX-38's line with a default of 1, or keyed by the findings loop's `hour` for `sample.hour`: TO5's part whose two samples fall in two hours that held no dropped count;
  - OX-36's line with a default of 1: TO6's restore overflow in the next hour, which held no samples-dropped count;
  - OX-32's and OX-33's lines with `max(1, ...)`: TO7's two put-back batches, within both buffers; either line with the other's text: TO6's restore overflows of two and one;
  - OX-29's and OX-30's lines, each with the other's `tickets.` field: TO6's two dropped keys against one dropped sample; OX-50's and OX-51's lines likewise: TO5's; OX-50's and OX-51's lines without the `dict(...)` copy: TO6's restored markers;
  - OX-2's line with `not isinstance(finding, TicketFinding)`: TO2's subclass;
  - OX-44's line with one more code, OX-8's line routing one more sampled code to the missing buffer, and OX-43's line without one work kind: TO1's finding of each code and of each work kind;
  - OX-41's and OX-42's lines with the warning's arguments in another order: TO7's `(2, 1, 4, 3)`.

**Expected to survive** (said so the orchestrator's oracle can confirm):
- the error-message strings and every docstring or comment;
- `_pending`'s second work-ticket line (`or self._ticket_dropped or self._ticket_samples_dropped`), as `or False`. Every path that adds to either dict adds to `_ticket_offered` in the same pending part: `offer_ticket` counts offered before either; `_restore` adds the batch's offered with its dropped counts; `_first` counts overflow of samples whose offers counted offered in the same pending period. So I expect this mutant to be equivalent; it has no row.
- (A1) OX-21's line with `tickets.findings` alone: equivalent. A sample is kept only under a key its offer counted, and `_restore` puts both back, so a part with a sample always holds a finding count.
- (A1) `if not isinstance(exc, Exception):` in `_write_without_ticket_rows` as `if False:` (the line occurs twice in the file, so it has no row): no test raises a `BaseException` that is not an `Exception` from a write, here or for `_flush`'s own branch since M3b. Recorded, not tested in this slice (§16, A1). (A2) For the same reason: OX-21's line with `BaseException` for `Exception`, and `_write_without_ticket_rows`'s `except BaseException as exc:` as `except Exception as exc:`.
- (A2) OX-21's line with its second `or` as `and` (`tickets.findings or (tickets.samples and tickets.missing)`): equivalent by the invariant of A1's item on `tickets.findings` alone (a part with a sample holds a finding count).
- (A2) OX-2's line with `not isinstance(off_loop, bool)` for `type(off_loop) is not bool`: equivalent; `bool` cannot be subclassed.
- (A2) each of the six `or` operators of `_pending`'s two work-ticket lines (OX-40's line and the line after it) as `and`. Such a mutant differs only when one of its two operands is truthy and every other operand of the chain is falsy, which three invariants exclude:
  - J1: `_ticket_findings`, `_ticket_samples`, `_ticket_missing`, `_ticket_dropped` and `_ticket_samples_dropped` are each non-empty only when `_ticket_offered` is (the item on `_pending`'s second line above);
  - J2: `_ticket_offered` is non-empty only when `_offered`, `_ticket_findings` or `_ticket_dropped` is: `start` marks `_offered` and `_ticket_offered` together; an accepted offer adds a key count or a dropped count after its offered count, with nothing between them that can raise for an exact finding; `_restore` adds the batch's counts back together;
  - J3 (the operator that joins M3c's `self._disagreements` to `self._ticket_findings`): `_disagreements` is non-empty only when `_offered` is: `offer` counts `_offered` before it keeps a disagreement, and `_restore` adds both back.

## 11. Verified Against Codebase (2026-10-30, read on `35045636`, tree `b6343ecb`)

```
git rev-parse HEAD HEAD^{tree} 1ae78c8a^{tree}   -> 350456361697..., b6343ecb5160..., a7fd7db1bb31...
git log --oneline -5                             -> 35045636 (scratch base: 07c526a1 + the M3d3b1 contract), 07c526a1, f26a0f04, 2f4d80f8 (M3d3b1 oracle stages), 1ae78c8a (M3d3a repair 1)
git status --short                               -> (nothing)
git diff --stat 1ae78c8a HEAD                    -> 11 files; DECISIONS.md, PROGRESS.md, the M3d3b1 contract, report.py, storage_declarations.py, store.py, and five tests; not recorder.py or service.py
git diff 1ae78c8a HEAD -- tests/test_ad1346_admission_shadow_parity.py tests/test_ad1346_admission_service.py
                                                 -> service: store.py allowlist and T14's last docstring sentence; parity: P6 and its bullet; neither touches recorder.py's allowlist or P13
Read src/probos/admission/recorder.py (whole; 285 lines by `wc -l`, corrected in A1)
  :73-76    COUNTER_NAMES, eight names
  :90       class ShadowRecorder; 12 direct defs (__init__, boot_id, offer, _hour_of, start, _run, stop, _flush, _restore, _pending, _failed, counters)
  :105-108  __init__'s _offered, _dropped, _samples_dropped, _totals
  :119-161  offer: late first, then counts and samples
  :170-179  start: _offered.setdefault(hour, 0), create_task
  :189-193  _run's comment "(_restore precedes _failed)"
  :195-218  stop's docstring and warning
  :232-248  _flush builds ShadowBatch from seven fields; restore before _failed
  :250-270  _restore, _pending
  no Lock and no call_soon_threadsafe in the file
Read src/probos/admission/service.py (whole, 274 lines)
  :19-23    docstring "nothing is refused or persisted"
  :147-148  shadow's `if self._recorder is not None:` / offer
  :166-203  hold; :190 `token = CURRENT_TICKET.set(issued.ticket)`
  :226-252  _check_ticket; :238 `self._tickets.check(ticket, effect=effect, presented_key=key)` (finding discarded); :239-240 off-loop count
Read src/probos/admission/tickets.py (whole)
  :143-164  TicketFinding; :158-160 __post_init__ checks operation and code membership only
  :167-172  TicketIssue(ticket, finding)
  :254-286  check returns the counted finding; :270-272 ticket_missing with presented_key only
  :442-450  _require: work kind in WORK_KINDS for issues
Read src/probos/admission/store.py :1-75, :160-260, :290-612
  :315-322  TicketSample(hour, recorded_at, finding, off_loop)
  :326-339  TicketBatch field order: findings, samples, missing, offered, dropped, samples_dropped
  :343-359  ShadowBatch.tickets default TicketBatch()
  :362-365  ticket_digest: value.encode("utf-8")
  :368-383  persisted_finding: _ISSUED_ID.fullmatch(raw) for ticket_id and parent_id
  :526-527  ticket ring rows built before the try (:538)
  :551-561  ticket statements, then commit; :562-564 rollback and re-raise
Read src/probos/admission/report.py (whole): :58-74 the five ticket_ queries
Grep taxonomy.py: :22 SEAM_MODEL_CALL, :27 WORK_KINDS, :73-88 TICKET_* codes, 12 in TICKET_REASON_CODES
Grep agent_stop.py: :60 SEAM_INTENT, :62 SEAM_TOOL, :68 SEAM_AGENTIC_RUN
Read src/probos/runtime.py :2920-2963   recorder built and started (:2936-2937), service built with loop=asyncio.get_running_loop() (:2959), same coroutine
Read src/probos/startup/shutdown.py :1396-1425, :1480-1514   AD-820 marker (:1405-1418) before close (:1494-1496), recorder stop (:1497-1500), store stop (:1502-1506)
Read src/probos/shutdown_integrity.py :1-60   check_previous_shutdown refuses after an unclean end unless --force-unclean
Grep scripts/check_architecture_principles.py: :187-188 SRP_MAX_BODY_LINES 500, SRP_MAX_DIRECT_METHODS 15; :559-564 direct FunctionDef/AsyncFunctionDef count
Grep scripts/gen_ad_ledger.py :122-141   status patterns and _HEAD_WINDOW 120
Read tests/test_ad1346_admission_service.py :20-119, :474-562   T13's attribute set (:493-496), T14 allowlists (:100-103 recorder), docstring (:507-513)
Read tests/test_ad1346_admission_shadow_parity.py :440-456   P13 at :455
Read tests/test_ad1346_admission_shadow_recorder.py :1-384   R1 counters equality (:171), R2 forbidden set (:178-181), _FailingStore (:59-74), R5 log levels (:236-238)
Read tests/test_ad1346_admission_ticket_sinks.py :1-280, :416-565   _OfflineGateway (:132-140), _ScriptedRun (:143-151), SK5 (:416), SK6 (:449), SK9 (:539)
Read tests/test_ad1346_admission_ticket_record.py :1-160   module docstring lines 7-9
Read tests/fixtures/ad1343_seam_census.py :25-94   RECORDED (:35-42)
Grep tests/fixtures/ad1346_shadow.py   :15 T0, :16 HOUR (an int), :28 refuse, :37 rows
Grep ^### DECISIONS.md   :1036 M3d3b1's heading, :1051 the following heading
Bash head -c 700 PROGRESS.md   M3d3b1's paragraph directly under the title
WebFetch https://docs.python.org/3.12/library/codecs.html  (2026-10-30)
  'surrogatepass' row: "Allow encoding and decoding surrogate code point (U+D800 - U+DFFF) as normal code point. Otherwise these codecs treat the presence of surrogate code point in str as an error." (codecs column includes utf-8)
  'strict': "Raise UnicodeError (or a subclass), this is the default."
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py   -> CEILING AD-1355 (GitHub issue titles), NEXT AD-1356
```

## Absence Verified (2026-10-30, run on `35045636`, tree `b6343ecb`)

```
CLAIM: nothing in src, tests or scripts names offer_ticket before this slice
RUN:   Grep '_tickets\.check|CURRENT_TICKET\.set\(issued|offer_ticket' in {src,tests,scripts}/**/*.py
FOUND: src/probos/admission/service.py:190, :238 (the two lines this slice edits); no offer_ticket
HOLDS: yes

CLAIM: no test or src text quotes stop's warning
RUN:   Grep 'were not written|not written before' in {src,tests,scripts}/**/*.py
FOUND: src/probos/admission/recorder.py:216 only
HOLDS: yes

CLAIM: no test reads a ShadowRecorder's vars
RUN:   Grep 'vars\((recorder|rec\b|shadow_recorder)' in tests
FOUND: nothing
HOLDS: yes

CLAIM: the services that tests build with a recorder have no ticket registry, so their hold and sink checks offer nothing
RUN:   Grep 'recorder=' in tests
FOUND: test_ad1346_admission_shadow_parity.py:317, :356; test_ad1346_admission_shadow_recorder.py:339, :351, :358 (none passes tickets=); the other hits are other classes' keywords
HOLDS: yes (the runtime's service is the one built with both: runtime.py:2959)

CLAIM: only the record test's docstring says the recorder builds batches without a work-ticket part
RUN:   Grep -i 'M3d3b2|without a work-ticket part|nothing in .src. fills|no producer' in {src,tests}/**/*.py
FOUND: tests/test_ad1346_admission_ticket_record.py:8 (and unrelated "no producer" hits in other subsystems)
HOLDS: yes (M2-01 repairs it)

CLAIM: tests that name the ticket tables are the store, record, parity and report tests
RUN:   Grep 'ticket_markers|ticket_findings' in tests (files)
FOUND: test_ad1346_admission_shadow_store.py, test_ad1346_admission_ticket_record.py, test_ad1346_admission_shadow_parity.py, test_ad1346_admission_shadow_report.py
HOLDS: yes; none of them drives a recorder against those tables

CLAIM: the architecture baseline has no row for ShadowRecorder or AdmissionService
RUN:   Grep 'ShadowRecorder|AdmissionService|admission/' docs/development/architecture-baseline.yaml
FOUND: nothing
HOLDS: yes

CLAIM: the seam census records no offer callee
RUN:   Read tests/fixtures/ad1343_seam_census.py:35-42
FOUND: RECORDED holds shadow_at, hold_at, check_at and the stop and agent-work names; no offer or offer_ticket
HOLDS: yes

CLAIM: recorder.py takes no lock and hands nothing to another thread
RUN:   Read recorder.py whole
FOUND: no Lock, RLock, call_soon_threadsafe or run_in_executor
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** no baseline row changes (there is none for either class).
  - `ShadowRecorder` goes from 12 to 14 direct methods (the trigger is above 15).
  - Its span grows from 196 lines to 301 (by `ast` on the pre-build run of M1's stage), below 500.
  - `AdmissionService` gains no method.
  - No `create_task` and no `connect` is added in `src`.
- **`check_store_registry.py --check`:** it reads every `src` module, `recorder.py` and `service.py` among them; this slice adds no `CREATE TABLE` text, no `storage_declarations.py` module and no connect call, so it finds the same stores (prediction until M1's gate).
- **`check_seam_contracts.py`:** not touched.
- **Config:** no field.
- **T13:** `AdmissionService`'s attributes are unchanged.
- **T14:** `recorder.py`'s allowlist gains `dataclasses` and `probos.admission.tickets` (M1-17). `service.py`'s is unchanged, and its logging and clock rules hold: the offers log nothing and read no `_clock`.
- **R1:** its `counters()` equality holds, because `dict.fromkeys(COUNTER_NAMES, 0)` grows with the names.
- **P13:** M1-16. **TO12** pins the appended names.
- **Sentences and tests that quote a set this slice changes:**
  - `recorder.py`'s module docstring (M1-01), the `COUNTER_NAMES` comment (M1-03), the docstrings of `start`, `stop` and `_restore`, and `_run`'s comment (M1-07 to M1-11);
  - `service.py`'s module docstring ("nothing is refused or persisted", M1-12), `hold`'s (M1-13) and `_check_ticket`'s (M1-15);
  - T14's docstring (M1-18);
  - the record test's docstring (M2-01).

  These stay true and are not edited:
  - `carrier.py` ("nothing is persisted", said of the carrier);
  - `tickets.py` ("it has no store and nothing restores it", said of the registry);
  - the declaration's notes ("Written by probos.admission.recorder.ShadowRecorder");
  - `store.py`'s docstrings;
  - `failures`'s docstring.

  M3d3b1's dated entries and its acceptance greps (`TicketBatch(` in `src`) are records of their date.
- **Test collection:** `git diff --name-status --diff-filter=AD <slice base>..HEAD -- 'tests/test_*.py'` lists exactly one `A` file, `tests/test_ad1346_admission_ticket_offers.py`.
- **D156's cost run** on M1's stage, before the review (orchestrator).

## 13. Prior Art and Blind Spots

**Internal (adopted):**
- M3b's write-behind recorder (D10, R1, `_restore` within buffers; `prompts/ad-1346-m3b-shadow-admission-store.md`) and M3c's disagreement restore: the work-ticket part copies both.
- AD-1213's rollback before a later commit (`_rollback_quietly`): D150's second write relies on it, because the first write left nothing behind.
- M3d3a's D128 (`off_loop`, the loop the sink checks run on) and the AD-1195 durable-events precedent it cites.
- M3d3b1's D138 to D141 and its register R52 and R53, refined here.
- AD-820's shutdown marker (`shutdown_integrity.py`): D153's crash-window count.
- M3d2's register R45: D152 places the hold offer before the carrier's `set`.

**External:**
- **Splitting a failed batch to isolate a bad record:** AWS Lambda's event source mappings have a `BisectBatchOnFunctionError` setting that splits a batch in two and retries when the function returns an error ([SDK reference](https://docs.aws.amazon.com/sdk-for-kotlin/api/latest/lambda/aws.sdk.kotlin.services.lambda.model/-event-source-mapping-configuration/bisect-batch-on-function-error.html); the main developer guide page was not fetched). Adapted: D150 splits once, at the boundary between the verdict part and the work-ticket part. Repeated halving is considered, deferred (D150, option 5).
- **Python's codecs** (3.12, fetched 2026-10-30, §11): UTF-8 treats a lone surrogate as an error unless `surrogatepass` is given. This bears on `ticket_digest` (register R60).
- `docs/research/reference-projects.md`, judged on 2026-10-30: no row bears on a write-behind recorder's failure handling (the rows are agent harnesses, orchestration and memory projects). None was searched (considered, deferred), and no row update is proposed.

**Blind spots** (register items in brackets):
1. A ticket part that raises on every write (D150).
2. A failure that clears between the two writes [R59].
3. Holds on a thread other than the flusher's [R58].
4. The crash window [R61].
5. A verdict part that raises holds the ticket part back [R62].
6. A raising offer in `hold` leaves the unit without a ticket of its own [R63].
7. A store that fails every write [R64].
8. A lone-surrogate id at `ticket_digest` [R60].
9. The offer's cost on every model and tool call (D156).
10. `ticket_late` is unreachable on the runtime's single-thread stop path (D154).

## 14. Diff Reviewer: properties to verify

1. **The verdict path is unchanged where no finding is involved.** A batch whose write raises and whose work-ticket part holds no finding count and no sample is put back by `_restore`, exactly as before. A `BaseException` that is not an `Exception` from the first write puts the batch back and propagates without a second write.
2. **D150.**
   - The second write runs only for an `Exception` and a part with counts or samples.
   - Its work-ticket part is `_as_dropped(...)`, which holds no finding count and no sample.
   - If the second write raises, the original batch (not the reduced one) is put back.
   - If it commits, `ticket_dropped` and `ticket_samples_dropped` gain exactly what the part lost.
3. **Bounds.**
   - `offer_ticket` adds no new key beyond `PENDING_KEY_LIMIT` and no sample beyond its buffer, and counts each overflow per hour and in total.
   - `_restore` keeps at most each buffer and counts the rest.
   - Re-adding keys has no limit, as for verdicts (register R10's class).
4. **The offer.**
   - Late is tested first.
   - The type, bool, exact-`str` and work-kind checks come before the clock read and any count.
   - It awaits nothing and calls no store, task, wait or I/O name (TO3).
5. **The service.**
   - The offers sit inside the existing `try` blocks: `hold`'s before `CURRENT_TICKET.set`, `_check_ticket`'s after the off-loop count.
   - Both compare `self._recorder` with None.
   - The service gains no attribute and no import.
6. **Threads.** No lock and no hand-off is added. Each offer is in the same function as its registry call.
7. **Test file hygiene** (properties of the file's text):
   - The new file reads no environment variable, imports or calls no `subprocess` or `socket`, and puts every data directory under `tmp_path` (§15).
   - TO8 and TO9 each start a worker thread through `asyncio.to_thread`, and TO11 boots and stops a `ProbOSRuntime`.

## 15. Acceptance criteria

- The updated files and the new file pass, and each §10 mutant is killed.
- `grep -nE "LOCALAPPDATA|AppData|environ|getenv|(import|from) (subprocess|socket)|(subprocess|socket)\.|create_subprocess|Popen" tests/test_ad1346_admission_ticket_offers.py` finds nothing.
- `grep -n "data_dir=" tests/test_ad1346_admission_ticket_offers.py` prints nine lines:
  - eight contain `tmp_path /`: the `identities`, `stops` and `store` fixtures, TO5 (two), TO6, TO7 and TO11;
  - the other is `_FailingStore`'s `super().__init__(data_dir=data_dir)`.
- `grep -rn "offer_ticket(" src/probos` prints three lines: `recorder.py`'s `def` and `service.py`'s two calls.
- `grep -nE "Lock\(|call_soon_threadsafe|run_in_executor" src/probos/admission/recorder.py` prints nothing.
- `git diff --stat <slice base>..HEAD -- src/probos/admission/store.py src/probos/admission/report.py src/probos/admission/storage_declarations.py src/probos/admission/tickets.py src/probos/admission/carrier.py src/probos/admission/seam.py src/probos/runtime.py src/probos/startup` prints nothing.
- The §12 `--check` scripts pass, D156's figures are recorded, and the broad gate's receipt is green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Corrections to this contract

A1 (2026-10-30, after the orchestrator's pre-build run and the M3d3a and M3d3b1 sweeps; read on `b647ca0a`, M3d3b1's candidate `4d6ce6f5` plus this contract) repairs:
- Defect 1, predictions since measured: the dry application (A1-1), the collected count (A1-3, A1-14), the method count and span (A1-5, A1-44), and §17, reduced to what was not confirmed then (A1-48). The lone surrogate is confirmed by execution and moves into register R60 (A1-49). D156's figures and the ledger check stay predictions.
- Defect 2, the base: M3d3b1 is built and not merged, and its candidate `4d6ce6f5`'s `src` and `tests` equal those of the read tree (A1-2). The records stay dated to `35045636`; §11's line count of `recorder.py` is corrected to 285 (A1-43).
- Defect 3, the sweeps:
  - Universals: §5's lists of callers and readers (A1-6 to A1-13).
  - Whole-line claims: none found. M3-01's last SEARCH line is still the only prefix.
  - Coverage claims wider than an assertion: TO3's and TO11's bullets and the module docstring are narrowed (A1-15, A1-18, A1-22). TO1, TO2, TO5, TO6, TO7 and TO9 are strengthened (rulings S; A1-16, A1-17, A1-19 to A1-21, A1-23 to A1-37), with rows OX-50 to OX-52 (A1-38 to A1-40) and the further mutants listed under "Pinned with no row" (A1-41).
  - Mutants that survive and are not tested: one equivalent and one untested branch (A1-42).
  - Fail-open text after a first mutation: D150's count of failed writes, and what "whole" covers (A1-4).
  - Worker threads in §14 and the data directories in §15 (A1-45, A1-46).
- Defect 4, summaries: 21 pairs and 12 cases are unchanged; the 49 rows become 52 (A1-38, A1-48).
- Text that lands: A1-15 to A1-37, all in the new file (§7.5.N). A1 changes no text of §7.1 to §7.4, §7.6 or §8.

A2 (2026-10-30, after the orchestrator's one-line sweep and the M3d3b1 review's classes; read on `e30b9e47`, M3d3b1's repaired candidate `a4ad2774` plus this contract with A1) repairs:
- The one-line sweep's 12 survivors (of 154 mutants of the lines this slice adds to `recorder.py` and `service.py`):
  - four are real gaps, ruled S, on lines that already have rows: `_as_dropped`'s samples-dropped default (TO5; A2-3, A2-12, A2-15), `_first`'s default (TO6; A2-4, A2-16 to A2-19) and `_restore`'s two `max(0, ...)` terms (TO7; A2-5, A2-22), listed under "Pinned with no row" (A2-27);
  - eight are recorded under "Expected to survive": A1's `BaseException` branch, OX-21's line with its second `or` as `and`, and `_pending`'s six `or` operators, now with the three invariants that prove them; A1's single invariant covered neither `_ticket_offered` nor `_disagreements` as the only truthy operand (A2-28).
- Survivors that a token sweep does not generate, found by A2's closed enumeration and ruled S: a code or work kind that no test offers (TO1; A2-1, A2-6, A2-9, A2-10); a `TicketFinding` subclass (TO2; A2-2, A2-8, A2-11); a sample keyed by the findings loop's hour, and dropped and samples-dropped fields swapped where their counts were equal (TO5 and TO6; A2-7, A2-13, A2-14, A2-17); either `max` line with the other's text where both overflows were one (TO6); the warning's arguments in another order (TO7; A2-21). Recorded: one more equivalent and two widened-class mutants of the untested `BaseException` branch (A2-28).
- Sentences about existing tests and scripts, re-read: §12's "its inputs are unchanged" for `check_store_registry.py` was false, since it reads every `src` module (A2-29). The sentences on R1, R2, T14, P13, the seam census and the stop warning's text hold.
- Universals: R63's "the unit runs with no ticket" and blind spot 6 were false when the carrier already held a ticket, which is TO9's own case (A2-30, A2-35); R64's "`stop` makes at most four" omitted the flusher's last flush (A2-36).
- Sentences the repair changes: §5's patched buffers (A2-23), §10's notes for OX-25, OX-26, OX-50 and OX-51 and A1's TO7 tuple (A2-24 to A2-26), §15's count (A2-31), and §17's items on A2's test edits and on the campaign of record (A2-33, A2-34). 21 pairs, 12 cases and 52 rows are unchanged; no decision or register row is added.
- Text that lands: A2-1 to A2-22, all in the new file (§7.5.N). A2 changes no text of §7.1 to §7.4, §7.6 or §8, and no `src` line.

A3 (2026-10-30, after M3d3b1's review rounds; read on `6a11747b`, this contract with A2 and its milestones applied by tool on M3d3b1's `a4ad2774`) repairs:
- Certifications of a whole unit: §14 item 7 is deleted and item 8 becomes item 7 (A3-16); the front matter's sentence on how each count of the head parts is measured is deleted (A3-5).
- Universals and claims wider than their evidence: the title, `PROGRESS.md`'s head and the `DECISIONS.md` paragraph no longer say that each finding is written (A3-1, A3-11, A3-13); D150's sentence in `PROGRESS.md` and `DECISIONS.md` names a finding count, as the code tests (A3-12, A3-14); §2's sentence on `offer`'s bounds is deleted (A3-6); §5's clause on the tests that named the `ticket_` tables is deleted (A3-8); TO1's bullet no longer says the sample holds the offer's wall time, which TO1's clock, at the first second of an hour, does not tell from the hour's start (A3-9); TO3's name says what its body checks (A3-10); §12's list of sentences that quote a changed set is not said to be complete (A3-15).
- A sentence about an existing test: D157's "(T13)" is deleted, since T13's body pins the attributes only, and A2's list of sentences that hold no longer names T13 (A3-7, A3-21).
- Records: the front matter drops M3d3b1's review round and the list of its amendments (A3-2, A3-4) and names the citations marked "on `35045636`" as records (A3-3); A1's paragraph names the candidate it compared (A3-19).
- Sentences a later edit made wrong: §15 names `_FailingStore`'s line without an ordinal (A3-17); A1's and A2's paragraphs say what each changed (A3-18, A3-20, this pair); §17's item on the campaign of record names A3's file (A3-23); R52 cites D149 to D159, as the front matter does (A3-24); the inherited open rows include what R53 leaves open (A3-25).
- A settled item: §17's item on A2's test edits, which the orchestrator's census of the oracle executed, is deleted, and A2's paragraph names those items without their numbers (A3-26).
- Text that lands: A3-9 and A3-10 in the new file (§7.5.N); A3-11 and A3-12 in M3-01, and A3-13 and A3-14 in M3-02 (§8).

A4 (2026-10-30, after the first cross-family review round; read on `62d2eb45`, tree `2e3e95e1`, the built candidate) repairs:
- A coverage attribution: §10's "Pinned with no row" bullet on the `_restore` and `_failed` calls is deleted (A4-17).
- Universals over a failure's members (an `Exception` or another `BaseException`; the prune or a write; the log call of either `_failed`; a check on the loop or handed over): `PROGRESS.md`'s D150 sentence is deleted and `DECISIONS.md`'s names an `Exception` (A4-14, A4-15); `_run`'s comment and §14 item 2 no longer say what precedes each `_failed` (A4-11, A4-20); §14 item 1 no longer places `_failed` after `_restore` (A4-19); D150's count of failed writes and its sentence that a finding or sample can never keep the verdicts from a write are deleted (A4-2, A4-3); D151, §5 and R63 name an `Exception` (A4-5, A4-10, A4-24); D152 no longer says a raising offer counts a failure and an `off_loop_checks` entry (A4-6); D153 no longer says what `flush_failures` counts of the failed writes or which is logged at WARNING (A4-7); R64 names an `Exception` and no longer counts `flush_failures` (A4-25); TO9's bullet and docstring name the `RuntimeError` it raises (A4-12, A4-13).
- Counts of what the code does: D156's count of the offer's operations is deleted (A4-9); D150's gloss of R64 is deleted (A4-4); blind spot 7 no longer counts writes (A4-18).
- Placement: §2's and `PROGRESS.md`'s sentences that placed the offers inside the `except Exception` are deleted (A4-1, A4-14).
- Settled by measurement: D156's "idle" is deleted (A4-8); `DECISIONS.md`'s D156 bullet, which said the figures were to be recorded below, is deleted (A4-16); §17's item on D156's figures is deleted and the items after it are renumbered (A4-22, A4-23); §12's bullet that called the ledger check a prediction is deleted, and so are the items that remained in §17, which now says "None." (A4-26, A4-27).
- Text that lands: A4-11 in `recorder.py` (M1-08's REPLACE, §7.1); A4-12 and A4-13 in the new file (§7.5.N); A4-14 in M3-01, and A4-15 and A4-16 in M3-02 (§8).

A5 (2026-10-31, after the second cross-family review round; read on `8c964792`, tree `5eb1e8b2`, the repaired candidate) repairs:
- A failure's members: D151's sentence that the recorder counts nothing for an offer that raises is deleted (A5-1).
- Placement: §12's parenthetical that placed the offers inside the three `except Exception` blocks is deleted (A5-2).
- A5-1 and A5-2 change this contract only: no line of `src`, of the tests, of `PROGRESS.md` or of `DECISIONS.md`.
- Recorded, not repaired (listed in the landing comment on #1604): `stop`'s docstring (M1-09's REPLACE) says that a write that raises an `Exception` is counted and logged by the flush and is not raised from `stop`; when a logging handler raises in that flush, its exception propagates from `stop` (F-212's class; injected only).

## 17. Claims not yet confirmed

None.

## For the register (#1604)

- **Advanced by this slice:**
  - property 8: the work ticket's service-written record, with producer (offered) and consumer (written) markers filled on a vessel;
  - property 5: the persisted `ticket_revoked` evidence for the run and the delegated child (TO10);
  - property 3: classified samples of every sampled code;
  - property 7's method (D156);
  - the persisted shadow evidence for registers R37 to R39 (`ticket_missing` by effect) and R49 (`off_loop`).
- **R52:** delivered, as refined by D149 to D159.
- **R53:** closed for the recorder's writes: `offer_ticket` refuses what the bound cannot hold (TO2). The store still checks nothing (M3d3b1's statement stands).
- **R58:** `hold`'s offer runs on its entry's thread. The recorder takes no lock, so an offer from a thread other than the flusher's loop thread is not synchronised with `_flush`'s detach and can be lost uncounted. This reasoning was not measured. `offer` has had the same exposure since M3b, wherever `shadow` runs off the loop. In the runtime the sink offers run on the flusher's loop (D152). The registry's own confinement of `hold` is register R31.
- **R59:** a write failure that clears between D150's two writes drops that flush's ticket counts and samples, counted in the markers and totals. The verdicts are written.
- **R60:** `ticket_digest` encodes with UTF-8's strict handler, so a `ticket_unknown` sample whose shown id holds a lone surrogate would fail its write. Executed on the pre-build run (CPython 3.12.13, the candidate's code): `"\ud800".encode("utf-8")` and `probos.admission.store.ticket_digest("\ud800")` each raise `UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 0: surrogates not allowed`. No test depends on it: TO5's poison is a `None` id. No producer in `src` reaches it while I11 holds: only `hold` sets the carrier, with registry-issued hex ids. D150 bounds it to one flush's ticket part. Repair (`surrogatepass`, which changes no digest of a valid `str`): considered, deferred to a follow-up of M3d3b1's store.
- **R61:** the crash window is not in the markers (D153). The property 8 report is to count boots whose end AD-820 did not mark clean. AD-820's marker is written before the recorder stops, so an end between the two is not flagged.
- **R62:** a verdict part that raises on every write still holds the ticket part back (D150 bounds one direction only). This was already true for verdict values.
- **R63:** an offer that raises an `Exception` in `hold` returns `NO_HOLD` with the issued entry registered. The unit runs under the carrier as it was: with no ticket when none was carried, so that its sink checks count `ticket_missing`, or under the enclosing unit's ticket (TO9's case) (injected only).
- **R64:** while every write raises an `Exception`, each flush whose part holds findings makes two writes; `stop`'s own flushes make at most four writes, after the flusher's last flush (at most two more) when the recorder was started.
- **Inherited and still open:** registers R10, R13 to R18, R19 to R23, R24 to R28, R32 to R34, R36, R37 to R45, R47 to R51, R53 for the store and for a wall clock that steps back, R54 to R57.
