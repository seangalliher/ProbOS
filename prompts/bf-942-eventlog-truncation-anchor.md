# BF-942 (#1706): A prune records a truncation anchor in the transaction of its delete and verify_chain starts from it, so the retained EventLog rows verify as truncated, not corrupt

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was unavailable), 2026-11-09
**Status:** ready to build on `origin/main` after BF-944 merges (reading tree `D:\ProbOS-worktrees\bf944-build` at `b8aedb22` = `origin/main` `8dced555` plus BF-944's five commits). **Oracle:** no test run (a read-only consult). An in-memory script applied the nine pairs of M2, the marker pair, the five tracker and document pairs (P3-3 and P3-3' each on its own blob) and the new test file to the LF blobs (each SEARCH once, every result parses, the blocks are ASCII), exec'd the patched `event_log.py` over the real tree and drove the cases by hand, with no pytest (section 11): on the base the 4 guards hold and the 17 class cases fail at their own `assert`; on M2's head all 21 hold; the ten mutants of section 9 fail the cases listed there (the campaign of record: section 9 gives the files and their sha256); 26 existing cases of `test_database_retention.py`, `test_ad490_eventlog_hash_chain.py` and `test_bf873_event_log_chain_concurrency.py` (without its subprocess and timing classes) hold on both. G2 and the architecture check were not run.
**Base blobs (`b8aedb22`):** `src/probos/substrate/event_log.py` `fb2bc226c16ef5971b0672423bcc1b90cb5d720a`, `docs/development/deterministic-ship.md` `1bfa5919be5c8a28ed6038c9d69052594b8eaa26`, `PROGRESS.md` `95a14bd7395a39c5a1b46af8972bd8fc9f6b63a5`, `DECISIONS.md` `93a70a31cc6be27899cf2b171320c8a21cbd619e`.
**Orchestrator oracle and amendments (2026-11-09):** BF-944 (#1717, PR #1777) had not merged when this oracle was built: the build tree is its pull request head `b8aedb22`, whose tree is the tree of the merge onto `origin/main` `8dced555` while main does not move (the build commits are made on the merge commit and their trees are compared with the oracle's). The four base blobs above are equal on it (`git rev-parse b8aedb22:<path>`). Every block (the nine pairs of P2-1 to P2-9, N2-1, the four pairs P3-1 to P3-4 with P3-3 chosen, and the new test file) was applied by tool, each SEARCH matching exactly once: PR #1713 is still open, the SEARCH of P3-3 occurs once in `deterministic-ship.md` on `origin/main` and that of P3-3' not at all. The two M2 files are byte-identical (LF sha256) to the campaign of record in section 9 (`event_log.py` `38b5df80...`, the test file `fcf5bd80...`, the base `event_log.py` `b5d3462c...`). G1 at M1: 4 passed and 17 xfailed; with `--runxfail` the 17 fail at 16 lines of the file, each an effect assert and none a premise line (the file has 4 premise asserts, which pass on the base). M0: the collected counts of the 37 files of G2 are equal on the M1 and M3 trees (2061 cases; the new file 21). G2 on the M3 head: 2059 passed, 2 skipped (`-n 0`); the new file 21 passed; `check_architecture_principles.py --check`, the ledger generator's `--check` and the ledger test (33 passed) are clean. A census of section 9's ten rows (the new file alone; baseline 21 passed) killed all ten, with 14, 11 and 10 failing cases for rows 1, 2 and 8, as the table says.
**Dependencies:** BF-944 merges first (only its two tracker entries are anchored; no code SEARCH is in a file its commits touch). **Tier:** M1 STANDARD (tests); M2 HIGH (data integrity; edits the event log's prune and verify); M3 STANDARD. **Estimated tests:** one new file, 21 cases (4 pass, 17 xfail at M1). **BF number:** BF-942, held by #1706 (open, `bug`); nothing new is allocated (section 11).

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` prints the first two blobs above, `git diff --stat 8dced555 HEAD -- src/probos/substrate/event_log.py docs/development/deterministic-ship.md` is empty, and the new test file does not exist. The `PROGRESS.md` and `DECISIONS.md` SEARCH text is BF-944's entry, so those match only after BF-944 is in. A SEARCH that does not occur exactly once is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **Pruning runs by default.** `EventLogConfig` defaults: `retention_days: 7`, `max_rows: 100_000`, `prune_interval_seconds: 3600.0` (`config_models/core.py:148-150`). `ProbOSRuntime._event_log_prune_loop` (`runtime.py:4078-4096`; wired `:2868`, started `startup/infrastructure.py:112-113`) sleeps one interval, then calls `EventLog.prune` (`:4089`); a failed prune is logged at DEBUG (`:4094`); AD-824's `CancelledError` arm re-raises (`:4096`).
2. **The cut.** `EventLog.prune` (`event_log.py:1250-1308`), under `_write_lock` (BF-873): an age `DELETE ... WHERE timestamp < ?` (`:1277`), a cap `DELETE ... WHERE id IN (the lowest ids)` (`:1289`), one unconditional commit (`:1300`): one implicit transaction. Nothing records where the chain was cut.
3. **The walk.** `verify_chain` (`:1211-1248`) starts at `GENESIS_HASH` (`:484`). Measured on the unfixed tree: 10 rows, `prune(0, 6)` deletes 4, `verify_chain()` returns `(False, 5)`, 5 being the first retained id.
4. **The age stage is not a head delete.** `timestamp < ?` removes every old-stamped row and `log()` stamps the wall clock (`:617`): after a clock step back an old-stamped row can sit behind a newer one, and the unfixed prune deletes it from the middle. Measured on the unfixed tree: six rows stamped 10, 10, 10, 1, 9 and 0.5 days ago, `prune(7, 0)` deletes 4, keeps ids 4 and 6, and `verify_chain()` returns `(False, 4)` (T4[clock] builds that case). No `(id, row_hash)` can name a cut in the middle.
5. **Restart at genesis.** The append uses genesis when the table has no tail (`:746-752`): measured, after every row was deleted the next row got id 11 (ids go on) and a genesis `prev_hash`.
6. **Callers of `verify_chain`.** No production call in `src`, `scripts`, `config` or `ui/src` outside the AuditLog's and the identity ledger's own `verify_chain` (section 11 lists the documents that name it). 24 call sites in 5 test files: 5 unpack two items, 19 compare with `(True, None)`.
7. **Every deleter of `events` rows** (the command is in section 11):

| Deleter | Deletes | The anchor |
|---|---|---|
| `prune`, age stage (`:1277`) | old-stamped rows | written first, naming the last row of the head run it deletes (D3) |
| `prune`, cap stage (`:1289`) | the lowest ids over the cap | written first, naming the last of them |
| `wipe` (`:1310`) | every row; no caller in `src` or `scripts` | cleared in the same transaction (D7) |
| `probos reset` (`__main__.py:3137-3141`, `RESET_TIERS[1]["files"]`) | the file `events.db` | the table is in the file: nothing to do |
| tests (`test_ad1129_eventlog_query_tool.py:1098` drops `events`) | test data | none |

## 2. Solution

`_SCHEMA` gains the one-row table `events_truncation_anchor(singleton, event_id, row_hash)`. `prune` gives each stage a boundary row and one helper, `_delete_head`, which writes the anchor (`INSERT OR REPLACE`) and then deletes every row up to the boundary, inside prune's one transaction; the age stage becomes the head run. `verify_chain` reads the anchor, starts the walk from its `row_hash`, and returns `ChainVerdict`, a two-item tuple subclass with `state` (`intact`, `truncated`, `broken`, `unanchored`) and `anchor_id`. `wipe` clears the anchor. The prune docstring and `deterministic-ship.md` invariant 4 stop calling the break "tracked separately". No row, hash, id, `_compute_row_hash` or append-path line changes.

## 3. Decisions

Options are ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; the top one is taken.

**D1. Where the anchor lives, and how an existing store gets it.**

| # | Option | Judgement |
|---|---|---|
| 1 | A one-row table in `events.db`, on the EventLog's own connection from its `ConnectionFactory`, created by `CREATE TABLE IF NOT EXISTS` in `_SCHEMA` (chosen) | Same transaction as the delete (the acceptance asks for it); it goes with the file (`probos reset` removes `events.db` by name); additive: `start()` runs `_SCHEMA` on every open (`:509`), so an existing store gains an empty table and no row, hash or column changes; a one-row primary-key read for a later reader (the unmerged ship-ledger note, `ship-ledger.md:93` on `origin/docs/ship-ledger-20261030`, wants `(id, row_hash)`) |
| 2 | A sidecar file | Not in the delete's transaction (a crash between them leaves rows gone and no anchor); outside `ConnectionFactory`; `probos reset` removes `events.db` and not the sidecar |
| 3 | A marker row in `events`, or a column on each row | The first appends and the second rewrites rows: the append path and the hashes change (forbidden); the first retained row would still link to a deleted row |

**D2. What the anchor holds and when it is written.**

| # | Option | Judgement |
|---|---|---|
| 1 | The id and `row_hash` of the last row a stage deletes; each stage that deletes runs `INSERT OR REPLACE` of the one row, then its delete, in prune's transaction under `_write_lock`; with both stages the cap stage's anchor is the last written; a stage with no boundary row writes nothing (chosen) | The acceptance as written; one anchor, at the latest cut; a failure rolls both back |
| 2 | One anchor from both rules before any delete | The cap rule counts the rows the age rule leaves: the arithmetic is done twice for the same result |
| 3 | One row per prune | Grows hourly; only the newest is ever read |

**D3. The age stage.**

| # | Option | Judgement |
|---|---|---|
| 1 | Delete the head run: the rows before the first row whose timestamp is not older than the cutoff (chosen) | The same rows whenever stamps rise with ids; after a clock step back an old-stamped row behind a newer one stays until that one ages out (L8), instead of the middle being cut |
| 2 | Keep `timestamp < ?` and anchor the highest id deleted | A hole in the middle that the walk reports as broken after a routine prune |
| 3 | Keep it and record each hole | The verifier would accept any deletion a record names: tamper evidence lost |

**D4. A prune that empties the table.**

| # | Option | Judgement |
|---|---|---|
| 1 | After an anchor, `verify_chain` accepts a first retained row that links to genesis (chosen) | The append restarts the chain there (section 1, item 5; unchanged), so an emptied table verifies as `truncated`; a false one costs a rehash of every later row (L1) |
| 2 | `prune` never deletes the newest row | Retention changes: `deleted` and the rows kept differ from today |
| 3 | The append chains to the anchor | The append path is out of scope |

**D5. The result of `verify_chain`.**

| # | Option | Judgement |
|---|---|---|
| 1 | `ChainVerdict`, a two-item `tuple` subclass with read-only `state` and `anchor_id` (chosen) | The 24 call sites are unchanged (table below) and the one entry point the issue names carries the anchor. Equality is the tuple's, so a `truncated` verdict equals `(True, None)` as an `intact` one does: a caller that needs the difference reads `state` |
| 2 | Keep the tuple and add `chain_state()` as the AuditLog does (AD-1278) | No compatibility risk, but a caller of `verify_chain()` cannot tell, the acceptance has `verify_chain()` name the anchor, and two methods share one walk |
| 3 | A three-item tuple or a dataclass | Breaks the 5 unpacks and the 19 comparisons |

The effect of each result shape on each existing consumer (the 24 sites are listed in section 11):

| Shape (state; tuple) | Tuple today | Call sites that reach it |
|---|---|---|
| no rows: `intact`; `(True, None)` | same | `test_ad490_eventlog_hash_chain.py:55` |
| whole from genesis: `intact`; `(True, None)` | same | the other 21 sites except the two below |
| a row fails, never pruned: `broken`; `(False, id)` | same | `test_ad490_eventlog_hash_chain.py:80`, `:94` |
| pruned, retained rows verify from the anchor: `truncated`; `(True, None)` | `(False, first_id)` | none: no site prunes before it verifies, except `test_bf873_event_log_chain_concurrency.py:310`, whose prune deletes nothing |
| pruned, a retained row fails or is missing: `broken`; `(False, id)` | `(False, first_id)` | none |
| pruned before this change: `unanchored`; `(False, first_id)` | same | none |
| the log is not open: `intact`; `(True, None)` | same | none |

**D6. A store pruned before this change has no anchor.**

| # | Option | Judgement |
|---|---|---|
| 1 | `unanchored` (chosen): a first row that does not link to genesis gives `(False, first_id)`, as today; the walk goes on from that row's own link | Never `intact`; the tuple is what every caller gets today; the rows after the cut are still checked, so an edit behind it is found (the unfixed walk stops at the first row); the label says what is known: history was cut and nothing records where |
| 2 | Status quo, "broken at its first row" | Same tuple; calls an innocent row corrupt and checks nothing after it |
| 3 | Write an anchor at upgrade from the first row's `prev_hash` | Blesses whatever head exists (trust on first use): the forgery the issue rules out for a rehash, one step removed |

**D7. `wipe()`.** Chosen: delete the anchor in `wipe`'s transaction. The table is empty, ids go on and the next row restarts at genesis (D4), so a kept anchor would read `truncated` beside rows that were never cut. Rejected: leave `wipe` alone (the genesis link D4 accepts would hide the stale anchor).

**D8. Tests.** Real `EventLog` files under `tmp_path`, `~` moved, no network; rows written by `log()` so the hashes are real; a control round ahead of each assertion that fails on the unfixed tree; the age cases move the module's clock; `state` is read with `getattr` so the file collects and fails at an `assert` on the unfixed tree. Rejected: a test of `_delete_head` alone (no seam from `log` through `prune` to `verify_chain`); a source-text test (it cannot tell a required line from the shipped one).

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-9, then N2-1 (removing the marker) | G2 |
| M3 | P3-1 to P3-4 (P3-3' replaces P3-3 in one case), ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf942_eventlog_truncation_anchor.py -q -n 0 -p no:randomly`. **Expected: 4 passed** (T0), **17 xfailed** (T1 to T7). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `PY -m pytest tests/test_bf942_eventlog_truncation_anchor.py tests/test_ad1129_eventlog_query_tool.py tests/test_ad1152_agentic_correlation.py tests/test_ad1195_durable_event_seam.py tests/test_ad1195_durable_producers.py tests/test_ad1224_durable_tool_start.py tests/test_ad1240_tool_result_delivery.py tests/test_ad1324_audit_terminal.py tests/test_ad1324_terminal_context.py tests/test_ad1328_s2a_run_command_tool.py tests/test_ad1328_s2b_tool_router_shell.py tests/test_ad1343_agent_stop_lift.py tests/test_ad1343_agent_stop_settle.py tests/test_ad1343_agent_stop.py tests/test_ad1347_s3_execution.py tests/test_ad1356_s1_input_errors.py tests/test_ad490_eventlog_hash_chain.py tests/test_ad664_eventlog_diagnostic.py tests/test_bf873_event_log_chain_concurrency.py tests/test_bf907_trust_identity.py tests/test_bf925_event_log_window.py tests/test_bridge_alerts.py tests/test_correction_runtime.py tests/test_database_abstraction.py tests/test_database_retention.py tests/test_event_log.py tests/test_feedback_engine.py tests/test_onboarding.py tests/test_orientation.py tests/test_proactive.py tests/test_self_mod_deps.py tests/test_ad1346_admission_store_census.py tests/test_ad1346_admission_store_family_census.py tests/test_ad1346_admission_store_writes.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py -q -n 0 -p no:randomly` (the new file; the 30 files that import `probos.substrate.event_log`; the AD-1346 files that read `ad1346_store_census`: section 11). (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file 21 passed; every other file 0 failed and collected counts equal M0; the check clean.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-942 M1: tests for the EventLog hash chain verifying from a truncation anchor after a prune, xfail until built (#1706)`
- **M2:** `BF-942 M2: prune records a truncation anchor in the transaction of its delete and verify_chain starts from it (#1706)`
- **M3:** `BF-942 M3: trackers, ledger and the ship invariant's gap (#1706)`; its body ends with the line `Closes #1706.`

## 6. Tests (`tests/test_bf942_eventlog_truncation_anchor.py`)

| Id | Cases | Covers (case label: function) | xfail until |
|---|---|---|---|
| T0 | 4 | Guards that pass on both trees. [no-op]: a prune that deletes nothing writes no anchor and changes nothing. [first row]: an edit to the first retained row is detected there. [failed delete]: a delete that fails rolls the anchor back with it (the same transaction). [cancel]: a cancelled prune (AD-824) leaves no open transaction and no anchor | none |
| T1 | 4 | The verdict. [unpruned]: `intact`, an edit `broken`. [cap]: after a cap prune (the control: the count, the kept rows untouched). [age]: after an age prune. [both]: both stages delete, one anchor at the last row deleted | M2 |
| T2 | 3 | [edit]: an edit to a retained row is detected at that row. [delete first], [delete middle]: a deleted retained row is detected, not mistaken for a truncation | M2 |
| T3 | 3 | [reopen]: a reopened store verifies the same. [two prunes]: one anchor at the latest cut, and a later prune that deletes nothing leaves it. [emptied]: a prune that empties the table, then appends | M2 |
| T4 | 2 | [clock]: a clock stepped back cannot make the age prune cut the middle. [wipe]: `wipe` clears the anchor | M2 |
| T5 | 1 | `log()` and `prune()` together stay serialized and the chain verifies | M2 |
| T6 | 2 | [pruned before]: a store pruned before the anchor existed is `unanchored`, never intact. [edit behind]: an edit behind its cut is still found | M2 |
| T7 | 2 | [forged]: a first retained row that does not follow the anchor's id is broken. [existing]: an existing store gains the table and no row changes | M2 |

**How each xfail case fails on the base** (the first failing `assert`; run by hand, section 11). T1[unpruned] `_seen(...) == ((True, None), "intact", None)` (the state is None); T1[cap] `verdict == (True, None)` (the base returns `(False, 5)`); T1[age] `_seen(...) == (..., "truncated", old[2])`; T1[both] `_anchors(log) == [...]` (the count 5 holds); T2[edit] `_seen(...) == ((False, ids[7]), ...)` (the base: `(False, ids[4])`); T2[delete first] and T2[delete middle] `_seen(...) == ((False, ids[victim + 1]), "broken", ids[3])` (the first differs in the state, the middle in the pair); T3[reopen] `_seen(...)`; T3[two prunes] and T3[emptied] `_anchors(log) == [...]`; T4[clock] `prune(...) == 3` (the base deletes 4); T4[wipe] `_seen(...) == (..., "intact", None)`; T5 `(pair, state) == (..., "truncated")`; T6[pruned before] `_seen(...) == ((False, ids[3]), "unanchored", None)`; T6[edit behind] `_seen(...) == ((False, ids[6]), "broken", None)` (the base: `(False, ids[3])`); T7[forged] `_seen(...) == ((False, ids[4]), "broken", ids[9])`; T7[existing] `cursor.fetchone() is not None`. The control lines before each (the counts, the kept rows, `verify_chain() == (True, None)` before the prune, the premises) hold on both trees.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf942_eventlog_truncation_anchor.py`:

```python
"""BF-942 (#1706): routine pruning leaves the EventLog's hash chain verifiable from a durable truncation anchor.

Real ``EventLog`` files under ``tmp_path``, ``~`` moved, no network. Rows come from ``log()`` (real hashes); the age
cases move the module's clock. The functions before the class pass on the unfixed tree (T0); the class holds the
cases it fails. No BF-942 name is imported: ``state`` and ``anchor_id`` are read with ``getattr`` (the unfixed tree
returns a plain tuple) and the anchor rows by a helper that finds no table there.
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from probos.substrate import event_log as event_log_module
from probos.substrate.event_log import EventLog

_NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


class _Clock(datetime):
    """The module's ``datetime`` with a settable ``now()``: ``log()`` stamps rows and ``prune()`` takes its cutoff from ``at``."""

    at = _NOW

    @classmethod
    def now(cls, tz=None):
        return cls.at.astimezone(tz)


@pytest.fixture(autouse=True)
def _moved_home(tmp_path, monkeypatch):
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))


def _clock(monkeypatch):
    """Install the clock; the function it returns sets the time to ``days_ago`` days before ``_NOW``."""
    monkeypatch.setattr(event_log_module, "datetime", _Clock)

    def at(days_ago: float = 0) -> None:
        monkeypatch.setattr(_Clock, "at", _NOW - timedelta(days=days_ago))

    at(0)
    return at


@asynccontextmanager
async def _opened(tmp_path, name: str = "events.db"):
    log = EventLog(db_path=tmp_path / name)
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _fill(log, count: int) -> list[int]:
    return [await log.log(category="c", event=f"e{i}", data={"i": i}) for i in range(count)]


async def _rows(log) -> list[tuple]:
    async with log._db.execute("SELECT id, prev_hash, row_hash FROM events ORDER BY id") as cursor:
        return [tuple(row) async for row in cursor]


async def _anchors(log) -> list[tuple]:
    """The anchor table's ``(event_id, row_hash)`` rows; none where the table does not exist (the unfixed tree)."""
    async with log._db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events_truncation_anchor'"
    ) as cursor:
        if await cursor.fetchone() is None:
            return []
    async with log._db.execute("SELECT event_id, row_hash FROM events_truncation_anchor") as cursor:
        return [tuple(row) async for row in cursor]


async def _sql(log, sql: str, *params) -> None:
    await log._db.execute(sql, params)
    await log._db.commit()


def _seen(verdict):
    """``(the pair, state, anchor_id)``; the last two are None on the unfixed tree's plain tuple."""
    return (tuple(verdict), getattr(verdict, "state", None), getattr(verdict, "anchor_id", None))


# ------------------------------------------------------------------
# T0: guards (pass on both trees)
# ------------------------------------------------------------------


async def test_a_prune_that_deletes_nothing_writes_no_anchor_and_changes_nothing(tmp_path):
    async with _opened(tmp_path) as log:
        await _fill(log, 5)
        before = await _rows(log)
        assert await log.prune(retention_days=7, max_rows=100) == 0
        assert (await _anchors(log), await _rows(log)) == ([], before)
        assert await log.verify_chain() == (True, None)


async def test_an_edit_to_the_first_retained_row_is_detected_there(tmp_path):
    async with _opened(tmp_path) as log:
        ids = await _fill(log, 8)
        assert await log.prune(retention_days=0, max_rows=5) == 3
        await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[3])
        assert await log.verify_chain() == (False, ids[3])


async def test_a_prune_whose_delete_fails_rolls_the_anchor_back_with_it(tmp_path):
    async with _opened(tmp_path) as log:
        await _fill(log, 8)
        before = await _rows(log)
        real = log._db.execute

        def failing(sql, *args, **kwargs):
            if str(sql).lstrip().startswith("DELETE FROM events WHERE"):
                raise RuntimeError("the delete failed")
            return real(sql, *args, **kwargs)

        log._db.execute = failing
        raised = None
        try:
            await log.prune(retention_days=0, max_rows=5)
        except RuntimeError as exc:
            raised = exc
        log._db.execute = real
        assert raised is not None, "premise: the delete must have been reached and failed"
        assert (await _rows(log), await _anchors(log)) == (before, [])
        assert await log.log(category="c", event="after") is not None
        assert await log.verify_chain() == (True, None)


async def test_a_cancelled_prune_leaves_no_open_transaction_and_no_anchor(tmp_path):
    async with _opened(tmp_path, "shared.db") as vessel, _opened(tmp_path, "shared.db") as blocker:
        await _fill(vessel, 6)
        await blocker._db.execute("BEGIN IMMEDIATE")
        task = asyncio.create_task(vessel.prune(retention_days=0, max_rows=3))
        await asyncio.sleep(0.2)
        assert not task.done(), "premise: the prune must still be waiting for the write lock"
        task.cancel()
        await asyncio.sleep(0.05)
        await blocker._db.execute("ROLLBACK")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await vessel.log(category="c", event="after") is not None
        assert (await _anchors(vessel), await vessel.count()) == ([], 7)
        assert await vessel.verify_chain() == (True, None)


# ------------------------------------------------------------------
# T1 to T7: the cases the unfixed tree fails
# ------------------------------------------------------------------


class TestTheChainSurvivesAPrune:
    # BF-942 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-942 M2 builds it")

    async def test_an_unpruned_chain_is_intact_and_an_edit_to_it_is_broken(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 5)
            assert _seen(await log.verify_chain()) == ((True, None), "intact", None)
            await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[2])
            assert _seen(await log.verify_chain()) == ((False, ids[2]), "broken", None)

    async def test_after_a_prune_the_chain_verifies_from_the_anchor_it_names(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            before = await _rows(log)
            assert await log.verify_chain() == (True, None)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            assert await _rows(log) == before[4:]
            verdict = await log.verify_chain()
            assert verdict == (True, None)
            ok, broken_at = verdict
            assert (ok, broken_at) == (True, None)
            assert _seen(verdict) == ((True, None), "truncated", ids[3])
            assert await _anchors(log) == [(ids[3], before[3][2])]

    async def test_after_an_age_prune_the_chain_verifies_from_the_last_old_row(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            old = await _fill(log, 3)
            at(1)
            await _fill(log, 2)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])

    async def test_when_both_stages_delete_one_anchor_names_the_last_row_deleted(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            await _fill(log, 3)
            at(1)
            await _fill(log, 7)
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=5) == 5
            assert await _anchors(log) == [(before[4][0], before[4][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", before[4][0])

    async def test_an_edit_to_a_retained_row_is_detected_at_that_row(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[7])
            assert _seen(await log.verify_chain()) == ((False, ids[7]), "broken", ids[3])

    @pytest.mark.parametrize("victim", [4, 6])
    async def test_deleting_a_retained_row_is_detected_not_mistaken_for_a_truncation(self, tmp_path, victim):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await _sql(log, "DELETE FROM events WHERE id = ?", ids[victim])
            assert _seen(await log.verify_chain()) == ((False, ids[victim + 1]), "broken", ids[3])

    async def test_a_reopened_store_verifies_the_same_way(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            anchors = await _anchors(log)
        async with _opened(tmp_path) as reopened:
            assert _seen(await reopened.verify_chain()) == ((True, None), "truncated", ids[3])
            assert await _anchors(reopened) == anchors

    async def test_two_prunes_keep_one_anchor_at_the_latest_cut_and_a_later_no_op_leaves_it(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 12)
            before = await _rows(log)
            assert await log.prune(retention_days=0, max_rows=9) == 3
            assert await log.prune(retention_days=0, max_rows=5) == 4
            assert await log.prune(retention_days=7, max_rows=100) == 0
            assert await _anchors(log) == [(ids[6], before[6][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[6])

    async def test_a_prune_that_empties_the_table_restarts_the_chain_and_it_still_verifies(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            old = await _fill(log, 3)
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert await _rows(log) == []
            assert await _anchors(log) == [(old[2], before[2][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
            await _fill(log, 2)
            first = (await _rows(log))[0]
            assert first[:2] == (old[2] + 1, EventLog.GENESIS_HASH), "premise: the append restarts at genesis"
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])

    async def test_a_clock_stepped_back_cannot_make_the_age_prune_cut_the_middle(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            for days_ago in (10, 10, 10, 1, 9, 0.5):  # the fifth row was stamped after the clock stepped back
                at(days_ago)
                await _fill(log, 1)
            ids = [row[0] for row in await _rows(log)]
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert [row[0] for row in await _rows(log)] == ids[3:]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[2])

    async def test_wipe_clears_the_anchor_with_the_events(self, tmp_path):
        async with _opened(tmp_path) as log:
            await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await log.wipe()
            assert await _anchors(log) == []
            await _fill(log, 2)
            assert _seen(await log.verify_chain()) == ((True, None), "intact", None)

    async def test_log_and_prune_together_stay_serialized_and_the_chain_verifies(self, tmp_path):
        async with _opened(tmp_path) as log:
            await _fill(log, 6)
            results = await asyncio.gather(
                log.prune(retention_days=0, max_rows=3),
                log.log(category="c", event="concurrent"),
                return_exceptions=True,
            )
            assert [r for r in results if isinstance(r, BaseException)] == []
            assert results[0] > 0, "premise: the prune must have deleted"
            pair, state, anchor_id = _seen(await log.verify_chain())
            assert (pair, state) == ((True, None), "truncated")
            assert [row[0] for row in await _anchors(log)] == [anchor_id]

    async def test_a_store_pruned_before_the_anchor_existed_is_never_reported_intact(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 8)
            await _sql(log, "DELETE FROM events WHERE id <= ?", ids[2])  # what the old prune did: no anchor
            assert _seen(await log.verify_chain()) == ((False, ids[3]), "unanchored", None)

    async def test_a_cut_head_with_no_anchor_does_not_hide_an_edit_behind_it(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 8)
            await _sql(log, "DELETE FROM events WHERE id <= ?", ids[2])
            await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[6])
            assert _seen(await log.verify_chain()) == ((False, ids[6]), "broken", None)

    async def test_the_first_retained_row_must_follow_the_anchor(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            before = await _rows(log)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await _sql(
                log,
                "CREATE TABLE IF NOT EXISTS events_truncation_anchor "
                "(singleton INTEGER PRIMARY KEY CHECK (singleton = 1), event_id INTEGER NOT NULL, row_hash TEXT NOT NULL)",
            )
            # The true hash, but an id that does not come before the retained rows.
            await _sql(log, "INSERT OR REPLACE INTO events_truncation_anchor VALUES (1, ?, ?)", ids[9], before[3][2])
            assert _seen(await log.verify_chain()) == ((False, ids[4]), "broken", ids[9])

    async def test_an_existing_store_gains_the_anchor_table_and_no_row_changes(self, tmp_path):
        async with _opened(tmp_path) as log:
            await _fill(log, 5)
            await _sql(log, "DROP TABLE IF EXISTS events_truncation_anchor")  # a store made before BF-942
        con = sqlite3.connect(tmp_path / "events.db")
        before = con.execute("SELECT * FROM events ORDER BY id").fetchall()
        con.close()
        async with _opened(tmp_path) as reopened:
            async with reopened._db.execute(
                "SELECT name FROM sqlite_master WHERE name = 'events_truncation_anchor'"
            ) as cursor:
                assert await cursor.fetchone() is not None
            async with reopened._db.execute("SELECT * FROM events ORDER BY id") as cursor:
                assert [tuple(row) async for row in cursor] == before
            assert await reopened.verify_chain() == (True, None)
```

### 7.2 M2

All pairs are in `src/probos/substrate/event_log.py`, applied in label order; each SEARCH occurs once in the LF blob (section 11).

**P2-1.** The schema: the end of `_SCHEMA`.
SEARCH:
```
CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
"""
```
REPLACE:
```
CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
-- BF-942: where the last prune cut the chain: the id and row_hash of the last row it deleted.
-- One row, written in the transaction that deletes the rows it names; empty until a prune deletes.
CREATE TABLE IF NOT EXISTS events_truncation_anchor (
    singleton   INTEGER PRIMARY KEY CHECK (singleton = 1),
    event_id    INTEGER NOT NULL,
    row_hash    TEXT    NOT NULL
);
"""
```

**P2-2.** The result type, before the class.
SEARCH:
```
class EventLog:
    """Append-only event log persisted to SQLite.
```
REPLACE:
```
class ChainVerdict(tuple[bool, int | None]):
    """What ``EventLog.verify_chain()`` found: ``(ok, broken_at)`` and its state (BF-942).

    Still a two-item tuple: ``ok, broken_at = await log.verify_chain()`` and ``== (True, None)`` read as they
    always did, and equality is the tuple's whatever the state. ``state`` is ``"intact"`` (no anchor; every row
    verifies from genesis), ``"truncated"`` (a prune's anchor exists and every retained row verifies from it;
    ``anchor_id`` is the last row that prune deleted; ``ok`` is True), ``"broken"`` (a row fails; ``broken_at``
    is its id; ``anchor_id`` is the anchor the walk started from, if any) or ``"unanchored"`` (no anchor, and the
    first retained row does not link to genesis: history was cut and nothing records where, as in a store pruned
    before BF-942; ``ok`` is False and ``broken_at`` is that first row; the rows after it are consistent).
    """

    _state: str
    _anchor_id: int | None

    def __new__(cls, ok: bool, broken_at: int | None, *, state: str, anchor_id: int | None = None) -> "ChainVerdict":
        verdict = super().__new__(cls, (ok, broken_at))
        verdict._state = state
        verdict._anchor_id = anchor_id
        return verdict

    @property
    def state(self) -> str:
        return self._state

    @property
    def anchor_id(self) -> int | None:
        return self._anchor_id

    def __repr__(self) -> str:
        return f"ChainVerdict{tuple(self)!r} state={self._state!r} anchor_id={self._anchor_id!r}"


class EventLog:
    """Append-only event log persisted to SQLite.
```

**P2-3.** `verify_chain`: signature, docstring, the anchor read.
SEARCH:
```
    async def verify_chain(self) -> tuple[bool, int | None]:
        """AD-490: Walk the events table by id; return (ok, broken_at).

        Returns (True, None) if every row's row_hash equals the recomputed
        hash of (prev row's row_hash || canonical_json(payload)). Returns
        (False, broken_id) on the first mismatch. Empty table -> (True, None).
        """
        if not self._db:
            return (True, None)
        sql = (
```
REPLACE:
```
    async def verify_chain(self) -> ChainVerdict:
        """AD-490: Walk the events table by id; return ``(ok, broken_at)`` and its state (``ChainVerdict``).

        Each row's ``row_hash`` is recomputed from its stored ``prev_hash`` and payload, and its ``prev_hash`` must
        be the row before it. The walk starts at genesis or, once a prune has recorded a truncation anchor (BF-942),
        at the anchor's ``row_hash``: the first retained row must come after the anchor's id and link to its hash, or
        to genesis when the prune left no row and the next append restarted the chain. Without an anchor, a first row
        that does not link to genesis is a cut head: the walk goes on from its own link and ends ``(False, first_id)``,
        ``unanchored``, if the rest verify, so an edit behind the cut is still found.

        It takes no lock: a prune that commits during the walk can make it report a break that is not there, so
        run it again before treating ``broken`` as tamper (BF-942 L3).
        """
        if not self._db:
            return ChainVerdict(True, None, state="intact")
        anchor = await self._read_truncation_anchor()
        anchor_id = anchor[0] if anchor is not None else None
        sql = (
```

**P2-4.** `verify_chain`: where the walk starts.
SEARCH:
```
        expected_prev = self.GENESIS_HASH
        async with self._db.execute(sql) as cursor:
            async for row in cursor:
```
REPLACE:
```
        expected_prev = anchor[1] if anchor is not None else self.GENESIS_HASH
        first = True
        detached_at: int | None = None
        async with self._db.execute(sql) as cursor:
            async for row in cursor:
```

**P2-5.** `verify_chain`: the first row, the verdicts, and the anchor reader.
SEARCH:
```
                stored_prev = row[11]
                stored_row_hash = row[12]
                if stored_prev != expected_prev:
                    return (False, row[0])
                recomputed = _compute_row_hash(prev_hash=expected_prev, payload=payload)
                if recomputed != stored_row_hash:
                    return (False, row[0])
                expected_prev = stored_row_hash
        return (True, None)

    async def prune(self, retention_days: int = 7, max_rows: int = 100_000) -> int:
```
REPLACE:
```
                stored_prev = row[11]
                stored_row_hash = row[12]
                if first:
                    first = False
                    if anchor_id is not None and row[0] <= anchor_id:
                        return ChainVerdict(False, row[0], state="broken", anchor_id=anchor_id)
                    if stored_prev != expected_prev:
                        if anchor is None:
                            detached_at = row[0]
                            expected_prev = stored_prev
                        elif stored_prev == self.GENESIS_HASH:
                            expected_prev = stored_prev
                if stored_prev != expected_prev:
                    return ChainVerdict(False, row[0], state="broken", anchor_id=anchor_id)
                recomputed = _compute_row_hash(prev_hash=expected_prev, payload=payload)
                if recomputed != stored_row_hash:
                    return ChainVerdict(False, row[0], state="broken", anchor_id=anchor_id)
                expected_prev = stored_row_hash
        if detached_at is not None:
            return ChainVerdict(False, detached_at, state="unanchored")
        if anchor_id is not None:
            return ChainVerdict(True, None, state="truncated", anchor_id=anchor_id)
        return ChainVerdict(True, None, state="intact")

    async def _read_truncation_anchor(self) -> tuple[int, str] | None:
        """``(id, row_hash)`` of the last row the last prune deleted, or None when no prune has deleted (BF-942)."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT event_id, row_hash FROM events_truncation_anchor WHERE singleton = 1"
        ) as cursor:
            row = await cursor.fetchone()
        return (row[0], row[1]) if row else None

    async def prune(self, retention_days: int = 7, max_rows: int = 100_000) -> int:
```

**P2-6.** `prune`: the docstring.
SEARCH:
```
        BF-873, deliberate and unfixed here: deleting rows severs the AD-490
        chain, so verify_chain() reports the retained suffix as corrupt at its
        first row. Repairing that needs a durable truncation anchor (the
        AD-1278 AuditLog._truncated_at pattern), which needs schema or sidecar
        state this concurrency fix is not allowed to add. Rehashing the
        retained rows would forge the audit chain and is not an option. Tracked
        separately; do not "fix" it by rehashing.
        """
```
REPLACE:
```
        BF-942: only the head of the chain is deleted, and each stage that
        deletes first records, in the same transaction, a truncation anchor
        naming the last row it deletes (id and row_hash); verify_chain() starts
        its walk there, so the kept rows verify as truncated, not broken at
        their first row (the AD-1278 AuditLog._truncated_at pattern; BF-873
        left this open, #1706). The age stage deletes the run of rows from the
        head that are older than the cutoff, not every row with an old
        timestamp: after a clock step back that would cut the middle. Kept rows
        are never rewritten or rehashed, which would forge the chain.
        """
```

**P2-7.** `prune`: the age stage.
SEARCH:
```
                # Age-based pruning
                if retention_days > 0:
                    from datetime import timedelta
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
                    cursor = await self._db.execute(
                        "DELETE FROM events WHERE timestamp < ?", (cutoff,)
                    )
                    deleted += cursor.rowcount
```
REPLACE:
```
                # Age-based pruning. BF-942: the head run of rows older than the
                # cutoff, so a clock step back cannot make it cut the middle.
                if retention_days > 0:
                    from datetime import timedelta
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
                    deleted += await self._delete_head(
                        self._db,
                        "SELECT id, row_hash FROM events WHERE id < "
                        "COALESCE((SELECT id FROM events WHERE timestamp >= ? ORDER BY id ASC LIMIT 1), ?) "
                        "ORDER BY id DESC LIMIT 1",
                        (cutoff, _INT64_MAX),
                    )
```

**P2-8.** `prune`: the cap stage.
SEARCH:
```
                    if total > max_rows:
                        excess = total - max_rows
                        cursor = await self._db.execute(
                            "DELETE FROM events WHERE id IN "
                            "(SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                            (excess,)
                        )
                        deleted += cursor.rowcount
```
REPLACE:
```
                    if total > max_rows:
                        excess = total - max_rows
                        deleted += await self._delete_head(
                            self._db,
                            "SELECT id, row_hash FROM events ORDER BY id ASC LIMIT 1 OFFSET ?",
                            (excess - 1,),
                        )
```

**P2-9.** The helper, and `wipe`.
SEARCH:
```
        return deleted

    async def wipe(self) -> None:
        """Delete all events. Used by probos reset."""
        if not self._db:
            return
        async with self._write_lock:
            try:
                await self._db.execute("DELETE FROM events")
                await self._db.commit()
```
REPLACE:
```
        return deleted

    async def _delete_head(self, db: DatabaseConnection, boundary_sql: str, params: tuple[Any, ...]) -> int:
        """Anchor the boundary row, then delete every row up to it, in prune's transaction (BF-942).

        ``boundary_sql`` selects ``(id, row_hash)`` of the last row to delete, or no row, and then nothing is
        written. Returns the number of rows deleted.
        """
        async with db.execute(boundary_sql, params) as cursor:
            boundary = await cursor.fetchone()
        if boundary is None:
            return 0
        await db.execute(
            "INSERT OR REPLACE INTO events_truncation_anchor (singleton, event_id, row_hash) VALUES (1, ?, ?)",
            (boundary[0], boundary[1]),
        )
        cursor = await db.execute("DELETE FROM events WHERE id <= ?", (boundary[0],))
        return cursor.rowcount

    async def wipe(self) -> None:
        """Delete all events and the truncation anchor (BF-942): the chain starts over at genesis."""
        if not self._db:
            return
        async with self._write_lock:
            try:
                await self._db.execute("DELETE FROM events")
                await self._db.execute("DELETE FROM events_truncation_anchor")
                await self._db.commit()
```

**N2-1.** `tests/test_bf942_eventlog_truncation_anchor.py`: remove the marker.
SEARCH:
```
    # BF-942 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-942 M2 builds it")

    async def test_an_unpruned_chain_is_intact_and_an_edit_to_it_is_broken(self, tmp_path):
```
REPLACE:
```
    async def test_an_unpruned_chain_is_intact_and_an_edit_to_it_is_broken(self, tmp_path):
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. BF-944's entry is the newest; the new one goes above it. Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

**BF-944 (2026-11-09), #1717 -- pool-built file reader, directory list and file search agents apply the runtime's read policy.**
```
REPLACE:
```
# ProbOS Progress

**BF-942 (DATE), #1706 -- routine EventLog pruning leaves the AD-490 hash chain verifiable from a durable truncation anchor.**
- **Base.** `EventLog.prune` deleted the head of the chain and recorded nothing, so after any prune `verify_chain` reported the retained rows as corrupt at their first row; the prune runs hourly by default (retention 7 days, cap 100,000 rows). BF-873 left it open ("tracked separately").
- **Fix.** A one-row table `events_truncation_anchor` in `events.db` holds the id and `row_hash` of the last row a prune deleted, written in the transaction of the delete; `verify_chain` starts its walk there and returns `ChainVerdict`, still a two-item tuple, whose `state` is `intact`, `truncated` (with `anchor_id`), `broken` or `unanchored` (a store pruned before this change). The age stage deletes the head run of old rows; `wipe` clears the anchor. No row, hash or append-path line changes. Contract `prompts/bf-942-eventlog-truncation-anchor.md`. Closes #1706.

**BF-944 (2026-11-09), #1717 -- pool-built file reader, directory list and file search agents apply the runtime's read policy.**
```

**P3-2.** `DECISIONS.md`. Append after BF-944's entry, the newest BF entry. Its last bullet occurs once.
SEARCH:
```
- *Residual.* L1 to L9 of the contract; with `read_roots` set and `~/.probos` unlisted, the todo and scheduler agents answer that their list could not be read (BF-961; L6). *Reversal.* Revert the BF-944 commits.
```
REPLACE:
```
- *Residual.* L1 to L9 of the contract; with `read_roots` set and `~/.probos` unlisted, the todo and scheduler agents answer that their list could not be read (BF-961; L6). *Reversal.* Revert the BF-944 commits.

### BF-942 -- Routine EventLog pruning leaves the hash chain verifiable from a durable truncation anchor (DATE, #1706)

- *Scope.* `substrate/event_log.py` (`events_truncation_anchor`, `ChainVerdict`, `verify_chain`, `prune`, `wipe`), `docs/development/deterministic-ship.md` (invariant 4), tests. Contract `prompts/bf-942-eventlog-truncation-anchor.md`.
- *D1 (where).* A one-row table in `events.db` on the EventLog's own connection, created by `_SCHEMA` on every open. Rejected: a sidecar (not in the delete's transaction; `probos reset` removes `events.db` by name); a marker row or a column per row (they change the append and the hashes).
- *D2, D3 (what, when).* The id and `row_hash` of the last deleted row, replaced in the transaction of each stage that deletes; a stage that deletes nothing writes nothing. The age stage deletes the head run older than the cutoff, so a clock stepped back cannot make it cut the middle.
- *D4 (an emptied table).* After an anchor, a first retained row that links to genesis verifies: the append restarts the chain there. Rejected: keeping the newest row; chaining the append to the anchor.
- *D5 (the result).* A two-item tuple subclass with `state` and `anchor_id`: the 24 call sites that unpack two items or compare with `(True, None)` are unchanged. Rejected: a three-item tuple; a second method beside it (the AuditLog's `chain_state`).
- *D6, D7 (no anchor; wipe).* A store pruned before this change reports `unanchored`, `(False, first_id)` as before, and the walk goes on from that row's own link so an edit behind it is found. Rejected: reporting `intact`; an anchor written at upgrade (it would bless today's head). `wipe` clears the anchor in its transaction.
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-942 commits (the table stays and is ignored).
```

**P3-3.** `docs/development/deterministic-ship.md`, invariant 4's known gaps (one table row; the SEARCH is part of its line).
SEARCH:
```
`EventLog.prune` severs the hash chain, so `verify_chain` reports the kept rows as corrupt (BF-873, documented and deliberately unfixed at `event_log.py:1250-1262`, "tracked separately"). Dream pruning
```
REPLACE:
```
A store pruned before BF-942 reports `unanchored` until its next prune deletes rows, and the anchor sits in `events.db` beside the rows it describes, so it shows what a prune recorded and does not guard against a writer of that file (BF-942, #1706). Dream pruning
```

**P3-3'.** Only if `origin/docs/ship-ledger-20261030` (PR #1713, commit `8f7b93ee`) has merged first: it rewrites that cell, so P3-3's SEARCH finds nothing and this pair stands in for it; use exactly one of the two. Same REPLACE.
SEARCH:
```
`EventLog.prune` severs the hash chain, so `verify_chain` reports the kept rows as corrupt (documented and deliberately left unfixed by BF-873 at `event_log.py:1250-1262`; now tracked as BF-942, #1706). Dream pruning
```
REPLACE:
```
A store pruned before BF-942 reports `unanchored` until its next prune deletes rows, and the anchor sits in `events.db` beside the rows it describes, so it shows what a prune recorded and does not guard against a writer of that file (BF-942, #1706). Dream pruning
```

**P3-4.** The same row, "provided today by" (the same text on both branches).
SEARCH:
```
`EventLog` is append-only and hash-chained, with `verify_chain` (`event_log.py:476-482`, `:1211-1248`).
```
REPLACE:
```
`EventLog` is append-only and hash-chained, with `verify_chain`, which starts at the truncation anchor a prune records, so a pruned log whose kept rows verify is reported as truncated, not as corrupt (`EventLog.prune`, `EventLog.verify_chain`; BF-942).
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited (`git grep BF-942` at the head finds nothing).

## 8. What this does NOT change

`_compute_row_hash`, `GENESIS_HASH`, `log`, `_insert_chained_row`, `_rollback_quietly` and every row, hash, id and column of `events`; the query, governed-query and count methods; the prune loop, its cadence, `config_models/core.py` and the retention defaults; `runtime.py`, `startup/`, `__main__.py` (`probos reset` removes the file); the security `AuditLog` and the identity ledger; production callers (none is added); `docs/research/warm-boot-fragmentation-design.md:37` (it names `(ok=True, broken_at=None)`, which still holds for `intact` and `truncated`); the roadmap; AD-1346's census rows (`event_log.py` is one file-level row, `System(SHIP, "the event log")`, with no count). OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/substrate/event_log.py | `cursor = await db.execute("DELETE FROM events WHERE id <= ?", (boundary[0],))` | `cursor = await db.execute("DELETE FROM events WHERE id < ?", (boundary[0],))` | T1[cap], T1[age], T1[both], T2, T3, T4, T5, T7[forged], T0[first row] (14 cases) |
| 2 | M2 | src/probos/substrate/event_log.py | `"INSERT OR REPLACE INTO events_truncation_anchor (singleton, event_id, row_hash) VALUES (1, ?, ?)",` | `"SELECT ?, ?",` | T1[cap], T1[age], T1[both], T2, T3, T4[clock], T5 (11 cases) |
| 3 | M2 | src/probos/substrate/event_log.py | `return ChainVerdict(False, detached_at, state="unanchored")` | `return ChainVerdict(True, None, state="unanchored")` | T6[pruned before] |
| 4 | M2 | src/probos/substrate/event_log.py | `if anchor_id is not None and row[0] <= anchor_id:` | `if False:` | T7[forged] |
| 5 | M2 | src/probos/substrate/event_log.py | `elif stored_prev == self.GENESIS_HASH:` | `elif False:` | T3[emptied] |
| 6 | M2 | src/probos/substrate/event_log.py | `if anchor is None:` | `if False:` | T6[pruned before], T6[edit behind] |
| 7 | M2 | src/probos/substrate/event_log.py | `"COALESCE((SELECT id FROM events WHERE timestamp >= ? ORDER BY id ASC LIMIT 1), ?) "` | `"COALESCE((SELECT id FROM events WHERE timestamp >= ? ORDER BY id DESC LIMIT 1), ?) "` | T1[age], T1[both], T3[two prunes], T4[clock], T0[no-op] |
| 8 | M2 | src/probos/substrate/event_log.py | `(excess - 1,),` | `(excess,),` | T1[cap], T1[both], T2, T3[reopen], T3[two prunes], T4[wipe], T7[forged], T0[first row] (10 cases) |
| 9 | M2 | src/probos/substrate/event_log.py | `await self._db.execute("DELETE FROM events_truncation_anchor")` | `await self._db.execute("SELECT 1")` | T4[wipe] |
| 10 | M2 | src/probos/substrate/event_log.py | `cursor = await db.execute("DELETE FROM events WHERE id <= ?", (boundary[0],))` | `await db.commit(); cursor = await db.execute("DELETE FROM events WHERE id <= ?", (boundary[0],))` | T0[failed delete] |

**Campaign of record.** Run by hand (no pytest) on the overlay of M2's head: base tree `b8aedb22`; `src/probos/substrate/event_log.py` after P2-1 to P2-9 (LF) sha256 `38b5df8066ec176566af0f071f72465776b76989e6d731a944d1fd36a87cd33e` (the base blob's is `b5d3462cb1f1d059c0e94fa41bc81436af7764c4ad293e4d568f077fc361bccd`); `tests/test_bf942_eventlog_truncation_anchor.py` after N2-1 (LF) sha256 `fcf5bd803acefb73f32dec365ea51ec02a82b1df9f470c4d7b95ebe5c4f7fcda` (the case bodies are N1-1's; N2-1 removes only the marker). Baseline 21 passed; every mutant fails the cases it lists and no other. A Builder whose two files match these hashes does not repeat it; if `event_log.py` differs, rerun all ten; if only the test file differs, rerun the rows whose cases changed. Not tabulated, for the cap: the `if not self._db:` guard of `_read_truncation_anchor`, the `_INT64_MAX` sentinel, `ChainVerdict`'s properties, and the documents of M3.

## 10. Recorded limits

- **L1.** The anchor is stored in the file it describes. A writer of `events.db` can forge an anchor and a matching cut, or rewrite the rows and every later hash; verification shows what a prune recorded and finds an edit or a deletion in the middle, it is not proof against that writer (the AuditLog's anchor has the same reach). An external witness (the sealing the unmerged ship-ledger note describes) is its own decision.
- **L2.** A hash chain alone cannot see newest rows deleted, or the table emptied, by a writer other than `prune`; after the table is emptied the next row restarts at genesis, which `verify_chain` accepts after an anchor (D4) and without one.
- **L3.** `verify_chain` takes no lock: holding `_write_lock` for the walk would queue `log()` behind it past its 5 s wait budget (`_CHAIN_WRITE_BUDGET_S`). A prune that commits during a walk can therefore make it report `broken` for rows that are not corrupt; no test drives that interleaving; reach: a caller that runs during the hourly prune; today only tests call it. The docstring says to run it again.
- **L4.** A store with rows written before AD-490 has rows with empty hashes; `verify_chain` reports `broken` at the first of them, before and after this change, until a prune deletes them.
- **L5.** A store pruned before this change reports `unanchored` until its next prune deletes a row; no anchor covers the rows deleted before, and the first anchor written names only its own cut.
- **L6.** The prune loop logs a failed prune at DEBUG and tries again an hour later (`runtime.py:4094`; unchanged): a vessel whose anchor write keeps failing stops pruning, each attempt rolled back, with only that DEBUG line to show for it. The log level is not changed here.
- **L7.** `wipe` has no production caller (section 11), so its anchor clearing is exercised by tests only; its docstring no longer says "Used by probos reset", which `probos reset` does not do (it removes the file).
- **L8.** After a clock step back, a row stamped before the step stays until the newer-stamped row ahead of it leaves the age window, as long as the step; the cap stage still bounds the table (100,000 rows by default).
- **L9.** Two processes pruning one `events.db` are not serialized: `_write_lock` is per process and `prune` does not take `BEGIN IMMEDIATE`; two prunes could commit their anchors out of order and the walk would report `broken`. `EventLog.prune` has one caller, the runtime's loop (section 11); reach: none today.
- **L10.** A future production caller of `verify_chain` must decide what `unanchored` means. Ranked: (1) report it as unknown (invariant 6) until the next prune writes an anchor; (2) treat `ok` False as a failure, which cries on every vessel pruned before this change until then. Not decided here.

## 11. Verified Against Codebase (2026-11-09, reading tree `D:\ProbOS-worktrees\bf944-build` at `b8aedb22`)

**Run by the Architect, read-only (CPython 3.12.13, win32, SQLite 3.50.4; scripts and scratch copies in the OS temp folder, outside every repository, removed afterwards; `-B`; no pytest run; the host was running the canonical gate, so nothing was timed):**

```
git rev-parse HEAD -> b8aedb225062e5a9348f064876d1b8d120e563bc; origin/main -> 8dced555; git diff --stat 8dced555 HEAD over event_log.py, deterministic-ship.md, test_bf873_event_log_chain_concurrency.py and test_database_retention.py -> empty; the reading tree was clean after the runs
the unfixed module driven by hand on a temp SQLite file: 10 rows, prune(0, 6) -> 4, verify_chain -> (False, 5); after DELETE FROM events the next log() -> id 11, prev_hash genesis, verify_chain -> (True, None)
this contract's blocks applied in memory to the LF blobs: the nine pairs of M2 (event_log.py, 1425 lines after), P3-1 (PROGRESS.md), P3-2 (DECISIONS.md), P3-3 and P3-4 (deterministic-ship.md at b8aedb22), P3-3' and P3-4 (the same file at origin/docs/ship-ledger-20261030 = 8f7b93ee): every SEARCH occurs once and every result parses or applies; N2-1's SEARCH occurs once in N1-1; the blocks are ASCII
the 21 cases of N1-1 driven by hand (asyncio.run per case, a tmp_path, a monkeypatch shim): the base 4 pass and 17 fail at their own assert (section 6), none with another exception; M2's head 21 pass; the ten mutants of section 9
26 existing cases driven by hand with a fixture shim, on the base and on M2's head: test_database_retention.py (TestEventLogPrune, TestEventLogWipe: 8), test_ad490_eventlog_hash_chain.py (8), test_bf873_event_log_chain_concurrency.py (TestChainSerialization, TestTransactionIsNeverLeftOpen but its cancelled-BEGIN case, TestRollbackQuietly: 10): all pass on both
sql_write_scan (AD-1346) over the base and the patched event_log.py: 4 and 5 points; STORE_WRITE_FILES holds the file as one row, System(SHIP, "the event log"), with no count (D220), and the file is not a scoped file
```

**Absence Verified (2026-11-09)**

```
CLAIM: BF-942 is held by #1706 only; the highest numbers are AD-1359 and BF-961
RUN:   scripts/ad_ceiling.py (exit 0); git log --all subjects and bodies for BF-942; git grep BF-942 at HEAD and at origin/main; prompts/bf-942* in each of the 120 worktrees of git worktree list; gh issue list --state all --search "BF-942 in:title"; the highest BF in git log --all subjects, in issue titles (1517 issues, all states) and in prompts/bf-*.md over the worktrees (6160 files); the roadmap.md Bug Tracker
FOUND: AD-1359, next AD-1360; one commit, 8f7b93ee, in its body only; no hit (exit 1) at HEAD or origin/main; 0 files in 120 worktrees; #1706 only (OPEN, bug); BF-961 in all three sources; the Bug Tracker's 11 rows end at BF-683 (it lags). 8f7b93ee (Oct 30 2026, by "Claude") is the one commit of origin/docs/ship-ledger-20261030, PR #1713 (open, "documents only"), not an ancestor of HEAD or of origin/main: its body says deterministic-ship.md invariant 4 now cites BF-942 (#1706) for the pruning break. It names the number the issue holds and allocates nothing; it edits the cell P3-3 edits (hence P3-3')
HOLDS: yes

CLAIM: no production caller of EventLog.verify_chain; its call sites are the 24 listed
RUN:   git grep -n -E "\bverify_chain\b" -- src scripts docs config ui/src; a per-line scan of the five test files that await it
FOUND: in src only identity.py:1122 and routers/identity.py:58 (the identity registry's), security/audit.py:236 and startup/finalize.py:4759 (the AuditLog's) and event_log.py; in docs deterministic-ship.md:52, docs/research/warm-boot-fragmentation-design.md:37 (a design that names (ok=True, broken_at=None)), an era-5 roadmap row (BF-040, identity) and a ledger-snapshot title. Tests that unpack two items: test_ad490_eventlog_hash_chain.py:55, :65, :80, :94 and test_ad1129_eventlog_query_tool.py:1985. Tests that compare with (True, None): test_ad1195_durable_event_seam.py:383, :453, :477 (compared at :484), :689; test_ad1224_durable_tool_start.py:1731, :1838, :1839, :1845, :2176, :2281, :3063, :3220; test_bf873_event_log_chain_concurrency.py:187, :198, :225, :310, :340, :444, :513. 5 + 19 = 24
HOLDS: yes

CLAIM: only the three DELETEs of event_log.py delete events rows; EventLog.prune has one caller and EventLog.wipe none outside tests; no test runs the real prune loop
RUN:   git grep -n -i -E "delete\s+from\s+events\b|drop\s+table[^\n]*\bevents\b|\bvacuum\b|truncate\s+table\s+events" -- src scripts tests config ui desktop docker tools docs; git grep -n -E "event_log\.prune|event_log\.wipe" -- src scripts; git grep -n -i -E "\bwipe\b" -- src scripts; git grep -n "_event_log_prune_loop" -- tests
FOUND: event_log.py:1277, :1289, :1316 and test_ad1129_eventlog_query_tool.py:1098 (a test drops the table); no VACUUM or TRUNCATE; runtime.py:4089 only; the other `wipe` hits are CognitiveJournal.wipe, an argparse flag and message text; no test names the loop (tests that call prune or wipe: test_bf873:262, :304, :357 and test_database_retention.py:75-127, :144)
HOLDS: yes

CLAIM: the new names are free, and no test reads the table set of events.db
RUN:   git grep -n -i -E "events_truncation_anchor|ChainVerdict|_read_truncation_anchor|_delete_head|truncation_anchor" -- src tests scripts docs config ui/src; git grep -n -E "sqlite_master|_SCHEMA\b|PRAGMA table_info\(events\)" -- tests src, read for events.db
FOUND: no hit (exit 1); the schema reads of events in tests are PRAGMA table_info(events) (test_ad490_eventlog_hash_chain.py:128, test_ad664_eventlog_diagnostic.py:22, :34, :62: columns, not tables); test_database_abstraction.py's fake connection drives start() and stop() only
HOLDS: yes
```

**Read, not run:** `config_models/core.py:146-150`; `runtime.py:2868`, `:4078-4096`; `startup/infrastructure.py:112-113`; `__main__.py:2658-2665`, `:3137-3141`; `storage/sqlite_factory.py:37` (`aiosqlite.connect`, legacy transaction control: the implicit transaction BF-873 describes); `protocols.py:325-372`; `security/audit.py:25-28`, `:139`, `:236-291`, `:983-985`; `substrate/event_log.py:51`, `:484`, `:509`, `:617`, `:744-770`, `:1211-1329`; `deterministic-ship.md:52`; the unmerged note `ship-ledger.md:19`, `:41`, `:70-71`, `:93` on `origin/docs/ship-ledger-20261030`. **Not measured:** a live vessel (no vessel, no real `events.db` and nothing under `%LOCALAPPDATA%\ProbOS\data` was read); a long walk's duration; `prune` on a table of 100,000 rows.

## 12. Prior Art and Blind Spots

- **Internal: adopted.** The AD-1278 `AuditLog` (`security/audit.py`): the anchor is the `(sequence, entry_hash)` of the last removed entry (`_truncated_at`, `:139`), the walk starts there (`verify_chain`, `:236-257`), and the states are `intact`, `truncated`, `broken` (`chain_state`, `:259-274`; "truncation is not tampering", `:25-28`). **Differs:** its anchor is memory, rebuilt at boot from the durable stream (`:983-985`); here it is a row in the file, written in the delete's transaction. Its `verify_chain` returns a bool and a second method carries the state; here the state rides on a two-item tuple subclass (D5). Its `mark_truncated` is forward-only and raises (`:276-291`); here the boundary is always a retained row, so the anchor only moves forward unless a row is re-inserted below it, which the walk reports (T7[forged]). EventLog ids are AUTOINCREMENT, not dense, so there is no evicted count. BF-873's rules are kept (the rollback covers the cancelled statement; the commit is unconditional: T0[cancel], T0[no-op]) and its test comment (`test_bf873_event_log_chain_concurrency.py:277-283`: a test must not pin the defect) is followed: no case requires a routine prune to break the chain; T6[pruned before] pins D6's `unanchored` for a store that has no anchor, by decision, not as the unfixed behaviour. **Rejected:** a sidecar, a marker row, a rehash, an anchor backfilled at upgrade. **External:** none consulted.
- **Blind spots handled.** The first retained row (T0[first row], T7[forged]); the table emptied (T3[emptied]); a clock stepped back (T4[clock]); `wipe` (T4[wipe]); reopen (T3[reopen]); a prune that deletes nothing (T0[no-op], T3[two prunes]); two prunes; `log()` beside `prune()` (T5); a failed delete and a cancelled prune (T0); a store pruned before this change, with and without an edit behind its cut (T6); an existing store opened by the new code (T7[existing]). No public accessor for the anchor is added: nothing but `verify_chain` reads it.
- **What discards a correct result.** A routine prune that cuts the middle (the clock: D3); a restart at genesis after an emptied table (D4); a stale anchor after a wipe (D7); a prune that commits during the walk (L3, recorded); a pre-AD-490 head (L4, recorded); an anchor the id check refuses (only a row re-inserted below it can: a prune's boundary is always a retained row). **Recorded:** L1 to L10.

## 13. Diff Reviewer: properties to verify

1. `prune`: both stages go through `_delete_head`; its `INSERT OR REPLACE` comes before its `DELETE`, neither commits, and prune's one commit (`:1300`) is still unconditional; a stage with no boundary row writes nothing; the age boundary is the head run (T4[clock]) and the cap boundary is `OFFSET excess - 1`.
2. `verify_chain`, for each state: trace the first-row block. A first row is accepted only when it links to the anchor's hash, to genesis after an anchor, or (no anchor) as `unanchored` from its own link; its id must exceed the anchor's; everything else is `broken`. `anchor_id` is None only without an anchor. No rows: `intact`, or `truncated` beside an anchor.
3. `ChainVerdict`: two items, tuple equality, `state` and `anchor_id` read-only properties; no production code calls `verify_chain` and the 24 test sites unpack or compare the result, so nothing there copies, pickles or serialises it.
4. `wipe`: both deletes before the one commit; BF-873's `test_wipe_rolls_back_before_suppressing_commit_failure` still passes.
5. `_SCHEMA`: the table; opening an existing store changes no row (T7[existing]).
6. The append path is untouched: `git diff` shows no hunk in `log`, `_insert_chained_row`, `_rollback_quietly` or `_compute_row_hash`.
7. M1: the file collects on the unfixed tree, imports no BF-942 name, and the 17 class cases fail at their own `assert`, never at a premise line; N2-1 removes the marker only.
8. The documents: P3-3 or P3-3' (exactly one applies), P3-4; no document still says "tracked separately" about the break.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **The issue's list:** after a real prune `verify_chain()` reports `truncated` naming the anchor (T1); an edit to a retained row is detected at that row (T0[first row], T2[edit]); a deleted retained row is detected, not mistaken for a truncation (T2); a reopened store verifies the same (T3[reopen]); a prune that deletes nothing writes no anchor and changes nothing (T0[no-op]); two prunes leave one anchor at the latest cut (T3[two prunes]); `log()` and `prune()` stay serialized and the anchor write is in the delete's transaction (T5, T0[failed delete], T0[cancel]); a store pruned before this change is reported `unanchored`, never intact (T6); no row hash, `_compute_row_hash` or append-path line changes (T1[cap] control, P2 diff).
- **Compatibility:** the 24 existing call sites of `verify_chain` pass unchanged (G2).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (review round 1, 2026-11-09)

Round 1 (`gpt-6.1-sol`, on the frozen head `a9b10b4c`) returned NOT READY on two P3 findings. This change introduced both, and A1 fixes both. P2-7, the mutation row 7 and the campaign of record in section 9 describe M2's head, as built before A1.

1. **The highest id (P3, injected-only).** P2-7's age boundary used `_INT64_MAX` as an exclusive bound when no row is recent, so the row whose id is 2**63 - 1 stayed after an age prune of an all-old table, where the base deleted it. It is reachable only with `sqlite_sequence` at the 64-bit ceiling. R1-1 selects the last row before the first recent one, or the last row when none is recent, with no sentinel: `id < (SELECT id FROM events WHERE timestamp >= ? ORDER BY id ASC LIMIT 1) OR NOT EXISTS (SELECT 1 FROM events WHERE timestamp >= ?)`, the cutoff bound twice. `_INT64_MAX` stays in use at two other places of the module. R1-3 adds `test_an_age_prune_deletes_the_row_with_the_highest_id_sqlite_allows` to the class (22 cases in the file): on M3's head it fails at its own assert, `assert await log.prune(retention_days=7, max_rows=0) == 2`, where the prune returns 1; after R1-1 it passes.
2. **A stale rationale (P3, ordinary).** The comment before prune's unconditional commit said that a routine no-op prune runs a zero-row DELETE and so opens a transaction. Since this change a stage with no boundary row writes nothing, so a no-op prune opens none (the reviewer's trace: BEGIN and COMMIT on the base, nothing here). R1-2 rewrites the comment; the commit stays unconditional (BF-873).

**Cost, measured** (the `sqlite3` module on the real `events` schema, best of seven, this host). The age boundary query now scans where the form it replaces sought by id. At 100,000 rows it took 4.8 to 10.1 ms, against 0.01 to 5.1 ms; at 1,000,000 rows 58 to 110 ms, against 0.01 to 56 ms. It runs once an hour under `_write_lock`. Both forms selected the same boundary row in every measured scenario (half old, none old, 99.9% old, all old).

**Checks.** The new file: 22 passed; with the four EventLog consumers next to it (`test_ad490_eventlog_hash_chain.py`, `test_bf873_event_log_chain_concurrency.py`, `test_database_retention.py`, `test_event_log.py`): 72 passed. The reviewer's age, atomicity, verdict and cost probes, rerun on A1's tree with their own premise asserts, all pass; the age probe's ceiling case now deletes both rows and anchors the highest id. The census of section 9 with row 7's line changed and a new row 11 (`"OR NOT EXISTS (SELECT 1 FROM events WHERE timestamp >= ?) "` mutated to `"OR (? IS NULL) "`): 11 of 11 killed on a baseline of 22 passed; rows 1 and 2 by 15 and 12 cases (the new case adds one to each), row 7 by 5, row 8 by 10, row 11 by 2 (the new case and `test_a_prune_that_empties_the_table_restarts_the_chain_and_it_still_verifies`). A1's files, LF sha256: `src/probos/substrate/event_log.py` `092e54fdbe138388b606eb12cc17ebba23ffc2773c414680970832c420dc7485`, `tests/test_bf942_eventlog_truncation_anchor.py` `549769612db29fb9b9f8fed84b78a48631843da11ac8caad6be78c1d8e26bf15`.
