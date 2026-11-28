# BF-1006 (#1870, F-757): test runs open SQLite with commit flushes off by default, the scheduler stops aborting on a lost worker, and the gate records what a lost worker leaves

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-28
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-28 (Amendment A1, after Diff Reviewer round 1)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-28 UTC (Amendment A2, after Diff Reviewer round 2)
**Revised by:** claude-architect, 2026-11-28 UTC (Amendment A3, wording only, after Diff Reviewer round 3 and the round-three brake decision "continue"), applied by the orchestrator
**Status:** ready to build (A3). **Owning issue:** #1870 (F-757). Commits say `Refs #1870.`

**Amendment A3 (round 3, REQUEST CHANGES, 1 finding; wording only, no code or test change; every SEARCH still applies to the clean base `4cf6fb5c`).**
- R3-1 (P3, ordinary reach, a regression of A2): **fixed.** The texts said that every statement the hook runs goes through `sqlite3.Connection.execute`; since A2 the timeout read runs on a base-class cursor (`Cursor.execute`), so three statements go through `Connection.execute` and one through that cursor (the same SQL, the same final connection state). Changed: the 6.1 module docstring (the file text), P32's D2 text, section 2 (S1), section 3 (D4), section 7 (the subclass row), section 9 item 1, and a note on the A1 history bullet F2 below. `no_commit_flush.py` has no executable change (docstring only). P31's PROGRESS text already says the PRAGMA runs through `Connection.execute` and the read on the hook's own cursor, so it is unchanged.

**Amendment A2 (round 2, REQUEST CHANGES, 9 findings; the orchestrator's dispositions upheld; every SEARCH still applies to the clean base `4cf6fb5c`).**
- R2-1 (P2, injected-only, a regression of A1's repair): **fixed.** The busy timeout is read on a base-class cursor of the hook's own (`sqlite3.Connection.cursor(connection)`) whose `row_factory` is `None`, closed in a `finally`; the connection's row factory is never read or set, and the other statements' rows are never fetched. New tests: the row-factory test (`dict-rows`, `tuple-rows`) and the aiosqlite row-factory test. Ruling on (b): `aiosqlite.connect(..., factory=...)` directly, because `default_factory.connect` takes no factory (`sqlite_factory.py`:37).
- R2-2 (P3, A1's tests): **fixed.** Both error-field fixtures gain a clean `gw1` exit; the R8, R9 and 8.1 descriptions now state what happens.
- R2-3 (P3): **fixed** in the CI consumer row (section 7). R2-4 (P3): **fixed** by the exemption for generator output (line 17, section 9 item 10, section 14 item 3). R2-8 (P3): **fixed**: the no-raise claims are qualified to ordinary exceptions in section 9 item 6 and in P7's comment and docstring (text only; P7's executable lines are byte-identical), and one 6.11 test is renamed for the same reason.
- R2-5, R2-6, R2-7, R2-9: **recorded** in section 13, Recorded follow-ups, with reach and the smallest fix.
- Pairs changed: 6.1 (whole file), 6.3 (whole file), P7 (comment and docstring), 6.11 (whole file), P31, P32; sections 7, 8.1-8.3, 9, 10, 12, 13, 14 and this header. Unchanged: S2's code, P2-P6, P8-P30, P33-P41, the receipt fields, the validator, the Gate workers line and the four commits.

**Amendment A1 (round 1 of the adversarial review, REQUEST CHANGES, 7 findings; every SEARCH still applies to the clean base `4cf6fb5c`).**
- F1 (P1, a connect to a locked database waited about twice its timeout): **fixed.** The hook brackets its PRAGMA with the busy timeout: it reads the connection's busy timeout, sets it to 0, runs `PRAGMA synchronous=OFF`, and puts back what it read in a `finally`. A connect that finds its database locked returns at once at SQLite's default level (FULL) with one WARNING. Rejected: exempting read-only opens (it repairs the doctor check, not the class: the orchestrator measured 1,094 ms read-only); skipping URIs; a per-statement timeout (none exists). The refusal stays a **WARNING**, not DEBUG: a connection left at FULL in a test run is exactly the condition this BF removes, so it must be visible, and the doctor check's test asserts the check's outcome, not the log. Section 8.2's sweep line is the evidence that no other test counts warnings while it holds a lock.
- F2 (P2, the PRAGMA went through a subclass's `execute`): **fixed.** Every hook statement goes through `sqlite3.Connection.execute(connection, ...)`. `RefusesThePragma` is replaced by tests of genuine SQLite refusals and a recording, intercepting subclass. (A2 moved the timeout read to a base-class cursor; see section 9 item 1b.)
- F3 (P2, a `down` record without `error` counted as clean): **fixed.** `_count_lost_workers` refuses a `down` record whose `error` is missing or neither null nor text; `""` counts as lost.
- F4 (P2, a failing log handler failed the connection): **fixed.** The warning is delivered inside its own guard (Swallow tier, justified inline).
- F5 (P2, an xdist attribute read outside the writer's guard): **fixed.** `_write_worker_record(build)` takes a callable and runs it inside its `try`; the hooks pass lambdas (a decorator would hide the hook arguments from pluggy). Ruling: a helper that has its own fallback keeps it (`_worker_name` -> `"unknown"`, `_error_text` -> `"<unprintable>"`); any other fault while building, rendering or writing drops that one record, and the wrapper's missing-`down` refusal is the backstop. The AST no-raise test stays; the behavioural tests are the evidence.
- F6 (P3, absolute documentation claims): **fixed.** The texts say the connection *default* changes: a store that sets its own level keeps it (the AD-1315 authority sets FULL and still flushes), a store that sets none (`ProfileStore`) runs at OFF, and 25 `src/probos` files set a level at all. The scheduler docstring's old paragraphs are qualified in P5.
- F7 (P3, two mutation rows misclassified): **fixed.** R2 and P2m are killed rows with named killers; V3 stays an equivalent survivor.
- Pairs changed: 6.1 (whole file), P2, 6.3 (whole file), P5, P7, P22, 6.11 (new tests), P31, P32; sections 1, 2, 3 (D4), 4 (S1's subject), 5, 7 (two consumer rows), 8.1-8.3, 9, 10, 12, 13. Unchanged: S2's code (P6, P13), P3, P4, P8-P12, P15-P21, P23-P30, P33-P41, the receipt fields, the validator, the Gate workers line and the four commits.
**Base:** main `4cf6fb5c47e071295c8342ae9e8d96c3cc3eb5bf`. Branch `fix/bf1006-gate-without-flush-20261128` (worktree `D:\ProbOS-worktrees\f1870`). **Number:** BF-1006. The enumeration at 02:41Z found these maxima: git log --all subjects 961; GitHub issue titles, all states (1,553 issues), 1005 (#1867); `prompts/bf-*.md` 1000 in the main checkout and 1004 across every worktree (BF-1003 and BF-1004 are parked, #1419); `docs/development/roadmap.md` 927. #1870's title carries BF-1006. Re-checked at drafting: `gh search issues "BF-1006"` finds only #1870, and this worktree's `prompts/bf-100*.md` end at 1002. No AD number is allocated.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new hand-written text is ASCII. A2: regenerated generator output (the ledger pair from `scripts/gen_ad_ledger.py`, a regenerated config reference or facade baseline) is exempt; it is never hand-edited (the ledger writes U+2014 in `open-ads-report.md`).
**Estimated tests:** 45 new items (A2; 42 at A1, 30 before) in two new files (16 and 24) and two existing ones (2 and 3). 4 tests are changed in place, 4 shared test fixtures gain the new fields, and 0 tests are removed (section 8.2 has the list).
**Scope:** one candidate with four commits and one gate (section 4). Production code under `src/probos` is untouched.
**Do not touch:** BF-932's tree (`D:\ProbOS-worktrees\b932-gate`, batch 1 frozen) and the speech orchestrator's worktrees.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| every pytest process (CI, focused runs, the gate) | SQLite commits flush to disk (the compiled default `synchronous=FULL` on each new connection; 25 `src/probos` files set their own level after connecting, and the other stores keep the default) and `os.fsync` syncs | Run A (#1870, 16 workers, TEMP on G:, unchanged head) lost 7 workers. Each stuck worker spent 88-115 s in SQLite commits at about 130 ms each, because the volume completed about 600 synchronous writes per second however many workers asked. pytest-timeout (`timeout = 180`, `pyproject.toml`:190) killed every worker 170-179 s after its last test started. Run B (fsync no-op, `synchronous=OFF`) lost 0, the same tests took 28-36 s, and commits took about 0.4 ms. At one worker beside a running gate there were 23,869 commits (about 820 per test) costing 31.7 s, 24% of the run |
| xdist 3.8.0 `scheduler/loadscope.py`:202-203 (`remove_node`) and :353-354 (`schedule()`) | reschedule every listed node, including a replacement that `add_node` (:163-164) listed but that has not registered its collection (:236) | `_assign_work_unit` pops a unit (:268) and then raises `KeyError` at :275. From `schedule()`, called by `DSession.worker_collectionfinish` (`dsession.py`:306) when another worker finishes collecting, the error is uncaught and the run aborts (exit 3, F-757's `KeyError: <WorkerController gwN>`). From `remove_node`, `DSession.worker_errordown` swallows it (`dsession.py`:242-245): the second crashed test is never reported, and the popped unit is never sent |
| `tests/fixtures/duration_scheduler.py`:312-316 | `DurationOrderedLoadFileScheduling._assign_work_unit` calls `super()` unconditionally | the project's scheduler inherits both failures |
| `scripts/run_test_gate.py`:1247-1254, :1371-1375 | requires worker manifests gw0..gw(N-1) and records `workers=expected_workers` | a lost worker whose replacement wrote `gwN.json` fails the gate, but nothing records which worker was lost, its error, or the test it was running. A worker that dies after it wrote its manifest leaves no crash item (xdist's `remove_node` returns `None` when nothing is pending, `loadscope.py`:182-183) and passes. The TEMP volume is recorded nowhere |
| `tests/test_ad1315_protected_execution_authority.py`:311-353 | stops the authority, then reads `PRAGMA synchronous` on a connection the TEST opens (:315, :330) and asserts 2 (:353) | `synchronous` is per connection, so this reads the connection default, not the authority's `FULL` (`execution/authority.py`:1511). Under S1 it reads 0 |

## 2. Overview

- **S1:** a plugin module `tests/fixtures/no_commit_flush.py` is installed from `tests/conftest.py`'s `pytest_configure` and removed in `pytest_unconfigure`. It wraps `sqlite3.connect`, passes every argument through and runs `PRAGMA synchronous=OFF` once on the new connection, with the busy timeout at 0 for that statement and put back afterwards, its three setting statements through `sqlite3.Connection.execute` itself (A1) and the timeout read on a base-class cursor of its own with no row factory (A2). A failing PRAGMA (a locked database included, which fails at once) logs a warning and the connection is returned at SQLite's default; a failing warning never fails the connection. It also makes `os.fsync` a no-op. `PROBOS_TEST_DURABLE_WRITES=1`, read once at configure, opts a run out. aiosqlite opens through `sqlite3.connect` in its worker thread (`aiosqlite/core.py`:466), so it is covered too. A store's own PRAGMA after connecting still wins. The AD-1315 test reads the authority's level on the authority's own connection.
- **S2:** `_assign_work_unit` returns at once for a node whose collection is not registered. That node gets work when it registers, because `worker_collectionfinish` calls `schedule()`. A lost worker's crash item is then returned and reported.
- **S3:** the wrapper's plugin writes a worker-exit log from the controller: `ready`, `down` (xdist's error and the worker's own exit status) and `crash` (the test in flight). The log goes to `logs/gates/<stem>.workers.jsonl`, named by `PROBOS_GATE_WORKER_EXIT_LOG`. The validation refuses a run whose log is missing an exit or shows a lost worker. `CollectionTotals` gains `workers_lost`. Every manifest records the TEMP volume, and the receipt gains a `run` block holding it. `wave-orchestrator.ps1`'s receipt validator checks both fields.
- **S4:** the Gate workers line names the cause, the exit log, the receipt fields and the fallback counts.

Rejected, one line each:
- The hook only in the gate wrapper (option a of the consult): the canonical gate would then differ from CI (`ci.yml`:77 runs plain pytest) and from focused runs.
- Lowering the default worker count (option d): the Gate workers line forbids it in place of a cause, and the cause is found.
- Moving TEMP to another volume (option c): the cliff is per volume (2026-11-04: 212-394 synchronous ops per second on each), so this only spreads it.
- A `--worker-exit-log` pytest option: `tests/test_gate_timing.py`:481-489 pins that the gate plugin adds no option. The path travels like `PROBOS_GATE_COLLECTION_DIR`.
- TEMP read in each worker and written to its manifest: it ripples into four manifest-shape tests. The child inherits the wrapper's TEMP, TMP and TMPDIR unchanged (`_subprocess_env`, :812-822; `_pytest_subprocess_env`, :825-836), so the wrapper's own `tempfile.gettempdir()` names the same directory. A test pins that premise.
- Catching `KeyError` around `super()._assign_work_unit`: the unit is already popped (:268) and would be assigned without being sent.
- A receipt schema 2: the new fields are additive. `repair_candidate.verify_gate_receipt` reads named fields only (`repair_candidate.py`:393-395), and the ps1 validator checks the new ones.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | The hook lives in the test suite (`tests/conftest.py`), not in the wrapper | One environment for CI, focused runs and the gate. CI gains the same speed-up |
| D2 | `PRAGMA synchronous=OFF` at connect only, and `os.fsync` a no-op | Run B measured the two together. A store's later PRAGMA wins, so the stores' tests still read their own levels. SQLite: "If the application running SQLite crashes, the data will be safe", and only an OS crash or power loss can lose it. No test simulates either |
| D3 | **Rule: no test asserts a connection default.** A test reads a store's level on the store's own connection, after the store set it | The only reader of a default was AD-1315's test (section 10, Absence Verified). The other readers read the store's connection |
| D4 | A failing PRAGMA logs a WARNING (logger `tests.fixtures.no_commit_flush`) and the connection is returned. A1: the PRAGMA runs with the busy timeout at 0 and the caller's timeout put back in a `finally`, those statements through `sqlite3.Connection.execute` (the timeout itself is read on a base-class cursor, A2); a locked database is a WARNING too; an exception while delivering the warning is swallowed | Log-and-degrade: the hook must never fail a connection, and it must never wait on a lock the caller has not yet bounded with its own busy timeout (`crew_enrollment_check.py`:43-47 sets 100 ms only after connecting) |
| D5 | The opt-out is `PROBOS_TEST_DURABLE_WRITES=1`, read once at configure. Only the value `1` opts out | It restores what production does. It is not a control |
| D6 | The S2 guard comes first in `_assign_work_unit`, before the one-shot order | No unit is popped for an unregistered node, and the order is applied on the first real assignment |
| D7 | The exit log goes through an environment variable, and the wrapper clears an inherited value (`_PYTEST_CONTROL_ENV`) | The no-option contract (`test_gate_timing.py`:481-489) and the hidden-control rule (`test_run_test_gate.py`:432-443) |
| D8 | `workers_lost` is a required `CollectionTotals` field. The validation raises when it is not 0, and it requires a `down` record for every expected worker | The count comes from evidence. A log that lost records refuses the run rather than passing it |
| D9 | The TEMP volume is recorded in every manifest (`GateResult.temp_volume`), success or not, and in the success receipt's `run` block | A failed run has no receipt, and F-757's triage needs the volume most there. Only the volume is recorded, because the directory names the user |
| D10 | The worker count stays `collection.totals.workers` (already written, :1373, and validated, `wave-orchestrator.ps1`:252, :255) | Recording it twice would add nothing |
| D11 | **Correction of the offline probe (`probe_keyerror.py`):** the exit-3 path is `schedule()` from `worker_collectionfinish`. The `remove_node` path is swallowed by `worker_errordown`, which loses the crash report. The guard repairs both, and S2 has one test for each | Read in `dsession.py`:238-248 and :274-306 |
| D12 | CodebaseIndex: no change. The AD-1270f memo (`tests/conftest.py`:128-140) made 1 real build of 3.06 s in one worker over 29 tests (orchestrator's measurement, 2026-11-28). Record this on #1870 as considered and deferred | The memo works. The 7 of 37 stack samples are each worker's first build |

## 4. Milestones and commits

Four commits on the branch, in this order. Each subject carries no `AD-` or `BF-` token and none of the words close, fix or resolve. Stage explicit paths only.

1. **S1** (6.1-6.4): `Test-run SQLite connections start without commit flushes and os.fsync is a no-op` (A1 wording: only the default changes). Paths: `tests/fixtures/no_commit_flush.py` (new), `tests/conftest.py`, `tests/test_bf1006_no_commit_flush.py` (new), `tests/test_ad1315_protected_execution_authority.py`.
2. **S2** (6.5-6.6): `Duration scheduler gives no work to a replacement worker until it has collected`. Paths: `tests/fixtures/duration_scheduler.py`, `tests/test_ad1270f_duration_scheduler.py` (P13 and P14 only).
3. **S3** (6.7-6.11, and P15-P16 of 6.6): `Gate wrapper writes a worker-exit log and records lost workers and the TEMP volume`. Paths: `scripts/run_test_gate.py`, `scripts/_gate_pytest_plugin.py`, `scripts/wave-orchestrator.ps1`, `tests/test_run_test_gate.py`, `tests/test_ad1299_s1a_repair_candidate.py`, `tests/test_ad1270f_duration_scheduler.py` (P15, P16), `tests/test_bf1006_gate_worker_exit_log.py` (new).
4. **S4 and trackers** (6.12-6.14): `Gate workers standing order names the exit log, the receipt fields and the fallback counts`. Paths: `.github/agents/orchestrator.agent.md`, `PROGRESS.md`, `DECISIONS.md`, and the regenerated ledger pair `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change.

The ledger: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`), after P31 and P32.

**Shared trackers.** The speech orchestrator merges into `PROGRESS.md`, `DECISIONS.md` and the ledger pair. At build time, anchor P31 on whatever `# ProbOS Progress` heading is there, and P32 on the newest `### ` heading of `DECISIONS.md` (read it with `rg -n "^### " DECISIONS.md | head -3`). At this draft's base that heading is BF-930's. Regenerate the ledger after a merge rather than resolving it by hand.

## 5. Builder: may and may not

- **May:** apply the pairs in section order (6.1 to 6.14; the P numbers are labels, not an order), write the new files in full, run `gen_ad_ledger.py`, `git diff --check` and `git diff --stat`. The orchestrator makes the four commits of section 4.
- **May not:** run tests, commit, run the gate, edit an unnamed file, add `skip`, `xfail` or a retry, reword an anchor, or change a test's expectation beyond its pair. If a SEARCH does not match exactly once, stop and report.
- **Hard stops (report, do not repair):**
  - a focused failure that traces to a test reading a connection's default `synchronous`, or to a test expecting `os.fsync` to raise or to be called through;
  - a focused failure that traces to the hook's WARNING (a test that counts warnings while it holds a lock), or a connect that still waits on a lock after A1 (section 13, blind spots);
  - any `KeyError` from the scheduler after S2;
  - any receipt consumer outside section 7 that breaks;
  - a test that fails only under `-n 16` (the Gate workers line governs).

## 6. The pairs

### 6.1 New file `tests/fixtures/no_commit_flush.py`

```python
"""BF-1006 (#1870): test-run SQLite connections start without commit flushes; ``os.fsync`` does nothing.

At 16 xdist workers the test volume completed about 600 synchronous writes per second however
many workers asked (#1870, runs A and B, 2026-11-28). A worker's boot-heavy first test spent
about half of its 80-180 s inside SQLite commits at about 130 ms each, and pytest-timeout
(180 s) killed seven workers. With the flushes off the same tests took 28-36 s and no worker
was lost.

What the hook does, from ``pytest_configure`` to ``pytest_unconfigure`` (``tests/conftest.py``):

* ``sqlite3.connect`` is wrapped. Every argument passes through unchanged. On the new
  connection the wrapper runs ``PRAGMA synchronous=OFF`` once, with the connection's busy
  timeout at 0 for that one statement and then put back to what it was, even when the
  statement fails. ``PRAGMA synchronous`` reads the schema, so on a database another
  connection holds it would otherwise wait the whole timeout before the caller could set a
  shorter one of its own; with the bracket it fails at once. The three statements that set the
  timeout and the level go through ``sqlite3.Connection.execute`` itself; the timeout is read
  on a cursor the wrapper makes with ``sqlite3.Connection.cursor`` and whose row factory it sets
  to ``None``. So a connection subclass's own ``execute`` or ``cursor`` neither sees nor changes
  any of the four, and the connection's row factory is neither called nor changed (A2).
  aiosqlite opens its connection through ``sqlite3.connect`` in its worker thread, so aiosqlite
  connections are covered too.
* ``os.fsync`` does nothing.

What it changes, and what it does not. It changes the level a connection starts with, not
every commit. A store that sets its own level after connecting keeps it: the AD-1315 authority
sets FULL on purpose and still flushes. A store that sets no level (``ProfileStore`` among
them) runs at OFF. So no test may assert a connection's default: a test reads a store's level
on the store's own connection, never on one it opened itself. A connection that finds its
database locked when it opens keeps SQLite's default (FULL). A write still reaches the
operating system's cache before the call returns, so every reader in the run sees it, and a
process that is killed keeps its data; only an operating-system crash or a power loss could
lose it, and no test simulates either. Connections that do not go through Python's ``sqlite3``
(ChromaDB's own SQLite) and child processes a test starts still flush.

A failing PRAGMA (a locked database, a file that is not a database, a connection opened inside
a transaction) logs a warning and the connection is returned as it is; when delivering that
warning fails, the connection is still returned. The hook never fails a connection.
``PROBOS_TEST_DURABLE_WRITES=1``, read once when pytest configures, leaves both functions as
they are.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable, Mapping
from typing import Any

OPT_OUT_ENV = "PROBOS_TEST_DURABLE_WRITES"
PRAGMA = "PRAGMA synchronous=OFF"

_LOG = logging.getLogger(__name__)
_originals: dict[str, Callable[..., Any]] = {}


def no_fsync(fd: Any) -> None:
    """``os.fsync`` for a test run: the bytes stay in the operating system's cache."""
    return None


def _turn_off_commit_flush(connection: sqlite3.Connection) -> None:
    """``PRAGMA synchronous=OFF`` on ``connection``, failing at once on a lock, through the base class."""
    # A2: the timeout is read on a cursor of the hook's own with no row factory, so the connection's row
    # factory (a caller's dict rows, a counter) is neither called nor changed; the base class's ``cursor``
    # keeps a subclass's override out of it. The other statements' rows are never fetched.
    reader = sqlite3.Connection.cursor(connection)
    reader.row_factory = None
    try:
        prior = int(reader.execute("PRAGMA busy_timeout").fetchone()[0])
    finally:
        reader.close()
    sqlite3.Connection.execute(connection, "PRAGMA busy_timeout=0")
    try:
        sqlite3.Connection.execute(connection, PRAGMA)
    finally:
        sqlite3.Connection.execute(connection, f"PRAGMA busy_timeout={prior}")


def _warn_default_kept() -> None:
    # Called from the ``except`` in ``connect``, so ``exc_info`` names the refusal.
    try:
        _LOG.warning(
            "BF-1006: %s failed on a new connection; it keeps SQLite's default",
            PRAGMA,
            exc_info=True,
        )
    except Exception:
        # Swallow: the warning is this path's only report and delivering it failed (a handler that
        # raises). The hook never fails a connection (D4), so the connection is returned without it.
        pass


def _without_flush(
    real_connect: Callable[..., sqlite3.Connection],
) -> Callable[..., sqlite3.Connection]:
    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        try:
            _turn_off_commit_flush(connection)
        except Exception:
            _warn_default_kept()
        return connection

    connect.__wrapped__ = real_connect  # type: ignore[attr-defined]
    return connect


def installed() -> bool:
    """Whether the hook is installed in this process."""
    return bool(_originals)


def install_no_commit_flush(environ: Mapping[str, str] | None = None) -> bool:
    """Install the hook unless ``PROBOS_TEST_DURABLE_WRITES=1``; return whether it is installed.

    ``environ`` defaults to ``os.environ``. A second call while it is installed changes nothing.
    """
    if _originals:
        return True
    source = os.environ if environ is None else environ
    if source.get(OPT_OUT_ENV) == "1":
        return False
    _originals["connect"] = sqlite3.connect
    _originals["fsync"] = os.fsync
    sqlite3.connect = _without_flush(sqlite3.connect)  # type: ignore[assignment]
    os.fsync = no_fsync
    return True


def uninstall_no_commit_flush() -> None:
    """Put back the two functions the hook replaced; nothing to do when it is not installed."""
    if not _originals:
        return
    sqlite3.connect = _originals.pop("connect")  # type: ignore[assignment]
    os.fsync = _originals.pop("fsync")
```

### 6.2 `tests/conftest.py`

**P1.** SEARCH:
```python
from tests.fixtures.recursion_limit_gc import gc_quiet_at_recursion_limit  # noqa: F401  (fixture; BF-986, #1754)
```
REPLACE:
```python
from tests.fixtures.recursion_limit_gc import gc_quiet_at_recursion_limit  # noqa: F401  (fixture; BF-986, #1754)
from tests.fixtures.no_commit_flush import install_no_commit_flush, uninstall_no_commit_flush
```

**P2.** SEARCH:
```python
# Windows: closing an asyncio loop must not pin an ephemeral TCP port in TIME_WAIT. Module level, so it is in
# force before any test builds a loop; it touches asyncio's self-pipe only, never a test's own socketpair --
# see tests/fixtures/abortive_self_pipe.py (WinError 10055 at test setup).
install_abortive_self_pipe()
```
REPLACE:
```python
# Windows: closing an asyncio loop must not pin an ephemeral TCP port in TIME_WAIT. Module level, so it is in
# force before any test builds a loop; it touches asyncio's self-pipe only, never a test's own socketpair --
# see tests/fixtures/abortive_self_pipe.py (WinError 10055 at test setup).
install_abortive_self_pipe()


def pytest_configure(config):
    """BF-1006 (#1870): SQLite connections start at ``synchronous=OFF`` and ``os.fsync`` does nothing, for the run.

    Installed before collection, so a connection a test module opens when it is imported is covered too; see
    ``tests/fixtures/no_commit_flush.py``. ``PROBOS_TEST_DURABLE_WRITES=1`` opts a run out. Only the connection
    default changes: a store's own ``PRAGMA synchronous`` after connecting still wins, so no test may assert a
    connection's default.
    """
    install_no_commit_flush()


def pytest_unconfigure(config):
    """BF-1006 (#1870): put back ``sqlite3.connect`` and ``os.fsync``."""
    uninstall_no_commit_flush()
```

### 6.3 New file `tests/test_bf1006_no_commit_flush.py`

```python
"""BF-1006 (#1870): the test suite's no-flush hook (``tests/fixtures/no_commit_flush.py``).

``tests/conftest.py`` installs the hook for the whole session, and these tests read what it changed on real
connections; every refusal they provoke is SQLite's own (A1). The opt-out test takes the hook down and puts it back in a
``finally``. SQLite's own connection default
is FULL (2) here and in CI: ``tests/test_ad1315_protected_execution_authority.py`` read 2 on a fresh connection on
both before this change.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from probos.storage.sqlite_factory import default_factory
from tests.fixtures import no_commit_flush as ncf

pytestmark = pytest.mark.skipif(
    os.environ.get(ncf.OPT_OUT_ENV) == "1", reason="BF-1006: this run opted out of the no-flush hook"
)

_OFF, _NORMAL, _FULL = 0, 1, 2
_DEFAULT_BUSY_TIMEOUT_MS = 5000  # sqlite3.connect's default timeout of 5.0 s


def _level(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA synchronous").fetchone()[0]


def _busy_timeout(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA busy_timeout").fetchone()[0]


def _assert_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    records = [record for record in caplog.records if record.name == ncf.__name__]
    assert len(records) == 1 and records[0].levelno == logging.WARNING, records
    assert "BF-1006" in records[0].getMessage()


def test_a_bare_connection_reads_synchronous_off(tmp_path: Path) -> None:
    assert ncf.installed(), "premise: tests/conftest.py installed the hook for this session"
    connection = sqlite3.connect(tmp_path / "bare.db")
    try:
        assert _level(connection) == _OFF
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("statement", "level"),
    [("PRAGMA synchronous=NORMAL", _NORMAL), ("PRAGMA synchronous=FULL", _FULL)],
    ids=["normal", "full"],
)
def test_a_stores_own_level_after_connect_wins(tmp_path: Path, statement: str, level: int) -> None:
    connection = sqlite3.connect(tmp_path / "store.db")
    try:
        assert _level(connection) == _OFF, "premise: the hook set OFF at connect"
        connection.execute(statement)
        assert _level(connection) == level
    finally:
        connection.close()


async def test_aiosqlite_and_the_store_factory_connect_through_the_hook(tmp_path: Path) -> None:
    async with aiosqlite.connect(str(tmp_path / "raw.db")) as raw:
        cursor = await raw.execute("PRAGMA synchronous")
        assert (await cursor.fetchone())[0] == _OFF
    store = await default_factory.connect(str(tmp_path / "store.db"))
    try:
        cursor = await store.execute("PRAGMA synchronous")
        assert (await cursor.fetchone())[0] == _OFF
    finally:
        await store.close()


def test_os_fsync_does_nothing_during_the_run() -> None:
    assert os.fsync is ncf.no_fsync
    assert os.fsync(-1) is None  # the real call raises OSError for a descriptor that is not open


def test_every_connect_argument_passes_through(tmp_path: Path) -> None:
    class Recording(sqlite3.Connection):
        pass

    by_keyword = sqlite3.connect(
        str(tmp_path / "keyword.db"),
        timeout=1.5,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,
        check_same_thread=False,
        factory=Recording,
        cached_statements=7,
        uri=False,
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    by_uri = sqlite3.connect((tmp_path / "uri.db").as_uri() + "?mode=rwc", uri=True)
    try:
        assert type(by_keyword) is Recording
        assert by_keyword.isolation_level is None
        assert by_keyword.autocommit == sqlite3.LEGACY_TRANSACTION_CONTROL
        assert _level(by_keyword) == _OFF
        assert _busy_timeout(by_keyword) == 1500, "the hook put the caller's timeout back"
        assert (tmp_path / "uri.db").is_file(), "the uri flag reached SQLite"
        assert _level(by_uri) == _OFF
    finally:
        by_keyword.close()
        by_uri.close()


@pytest.mark.parametrize("refusal", ["not-a-database", "inside-a-transaction"])
def test_a_genuine_refusal_logs_one_warning_and_returns_the_connection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, refusal: str
) -> None:
    """SQLite itself refuses the PRAGMA: the file is not a database, or Python opened a transaction at connect
    (``autocommit=False``) and SQLite does not change the safety level inside one."""
    path = tmp_path / "refused.db"
    if refusal == "not-a-database":
        path.write_bytes(b"this is not an SQLite database file. " * 64)
    with caplog.at_level(logging.WARNING, logger=ncf.__name__):
        if refusal == "not-a-database":
            connection = sqlite3.connect(path)
        else:
            connection = sqlite3.connect(path, autocommit=False)
    try:
        _assert_one_warning(caplog)
        if refusal == "inside-a-transaction":
            assert _level(connection) == _FULL, "the refused PRAGMA left SQLite's default"
            assert _busy_timeout(connection) == _DEFAULT_BUSY_TIMEOUT_MS, "the timeout is back after the refusal"
    finally:
        connection.close()


def test_a_locked_database_fails_the_pragma_at_once_and_keeps_the_callers_timeout(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """``PRAGMA synchronous`` reads the schema. Run plainly on a database another connection holds, it waited longer
    than the caller's whole timeout (round 1: 7.84 s for the doctor check's read, whose own 0.1 s busy timeout comes
    only after the connect). With the busy timeout at 0 for that statement it fails at once."""
    path = tmp_path / "locked.db"
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("CREATE TABLE t (x)")  # rollback-journal mode, SQLite's default
        holder.execute("BEGIN EXCLUSIVE")
        with caplog.at_level(logging.WARNING, logger=ncf.__name__):
            started = time.monotonic()
            connection = sqlite3.connect(path, timeout=2.0)
            elapsed = time.monotonic() - started
    finally:
        holder.close()  # closing the connection rolls the open transaction back
    try:
        assert elapsed < 1.0, f"the connect waited {elapsed:.2f}s on the lock"
        assert _busy_timeout(connection) == 2000, "the caller's timeout is back"
        assert _level(connection) == _FULL, "a connection that found the database locked keeps SQLite's default"
        _assert_one_warning(caplog)
    finally:
        connection.close()


def test_the_hook_runs_its_statements_on_the_base_class(tmp_path: Path) -> None:
    """A subclass that records and intercepts ``execute`` neither sees the hook's statements nor stops them."""

    class Intercepting(sqlite3.Connection):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self.seen: list[str] = []

        def execute(self, sql: str, *args: object) -> sqlite3.Cursor:  # type: ignore[override]
            self.seen.append(sql)
            if sql.upper().startswith("PRAGMA"):
                return super().execute("SELECT 0")  # swallows every PRAGMA it is handed
            return super().execute(sql, *args)

    connection = sqlite3.connect(str(tmp_path / "subclass.db"), factory=Intercepting, timeout=1.5)
    try:
        assert type(connection) is Intercepting
        assert connection.seen == [], "the hook's statements bypass the subclass"
        level = sqlite3.Connection.execute(connection, "PRAGMA synchronous").fetchone()[0]
        timeout = sqlite3.Connection.execute(connection, "PRAGMA busy_timeout").fetchone()[0]
        assert (level, timeout) == (_OFF, 1500)
    finally:
        connection.close()


def _caller_rows(shape: str) -> tuple[type[sqlite3.Connection], Callable[..., Any], list[str]]:
    """A connection subclass whose ``__init__`` sets a row factory, as a caller's may. ``made`` records each row the
    factory builds and each call of the subclass's ``cursor``. ``dict-rows`` builds dicts keyed by column name (so
    ``row[0]`` raises ``KeyError``); ``tuple-rows`` returns the plain tuple."""
    made: list[str] = []

    def make_row(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> Any:
        made.append("row")
        if shape == "dict-rows":
            return {column[0]: value for column, value in zip(cursor.description, row, strict=True)}
        return row

    class Rows(sqlite3.Connection):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.row_factory = make_row

        def cursor(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:  # type: ignore[override]
            made.append("cursor")
            return super().cursor(*args, **kwargs)

    return Rows, make_row, made


def _only_value(row: Any) -> Any:
    values = list(row.values()) if isinstance(row, dict) else list(row)
    assert len(values) == 1, row
    return values[0]


def _hook_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == ncf.__name__]


@pytest.mark.parametrize("shape", ["dict-rows", "tuple-rows"])
def test_the_callers_row_factory_is_neither_called_nor_changed_by_the_hook(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, shape: str
) -> None:
    """A2 (Diff Reviewer round 2): the A1 hook read the busy timeout through the connection's row factory, so a
    caller's dict rows made ``[0]`` raise ``KeyError`` (the connection stayed at FULL, with a warning) and a counting
    factory was called during connect. The hook now reads it on a cursor of its own with no row factory."""
    rows, make_row, made = _caller_rows(shape)
    with caplog.at_level(logging.WARNING, logger=ncf.__name__):
        connection = sqlite3.connect(str(tmp_path / "rows.db"), factory=rows, timeout=1.5)
    try:
        assert made == [], "the hook built no row through the caller's factory and called no override of cursor"
        assert _hook_records(caplog) == []
        assert connection.row_factory is make_row, "the caller's row factory is still the connection's"
        assert _only_value(connection.execute("PRAGMA synchronous").fetchone()) == _OFF
        assert _only_value(connection.execute("PRAGMA busy_timeout").fetchone()) == 1500
    finally:
        connection.close()


async def test_aiosqlite_hands_the_callers_factory_to_the_hook_and_its_rows_are_left_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The same through ``aiosqlite.connect``, which passes ``factory`` to ``sqlite3.connect`` in its own thread. The
    store factory (``default_factory.connect``) takes no factory, so this is how a caller's row factory reaches it."""
    rows, make_row, made = _caller_rows("dict-rows")
    with caplog.at_level(logging.WARNING, logger=ncf.__name__):
        async with aiosqlite.connect(str(tmp_path / "rows.db"), factory=rows, timeout=1.5) as connection:
            assert made == [], "the hook built no row through the caller's factory"
            assert connection.row_factory is make_row
            cursor = await connection.execute("PRAGMA synchronous")
            assert _only_value(await cursor.fetchone()) == _OFF
            cursor = await connection.execute("PRAGMA busy_timeout")
            assert _only_value(await cursor.fetchone()) == 1500
    assert _hook_records(caplog) == []


def test_a_failing_log_handler_does_not_fail_the_connection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    called: list[str] = []

    class Fails(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            called.append(record.getMessage())
            raise RuntimeError("the handler fails")

    caplog.set_level(logging.WARNING, logger=ncf.__name__)
    handler = Fails(logging.WARNING)
    logger = logging.getLogger(ncf.__name__)
    logger.addHandler(handler)
    try:
        connection = sqlite3.connect(str(tmp_path / "refused.db"), autocommit=False)  # refused inside a transaction
    finally:
        logger.removeHandler(handler)
    try:
        assert len(called) == 1, "premise: the warning reached the failing handler"
        assert _level(connection) == _FULL
    finally:
        connection.close()


def test_a_file_that_is_not_a_database_still_opens_and_fails_at_first_use(tmp_path: Path) -> None:
    path = tmp_path / "not-a-database.db"
    path.write_bytes(b"this is not an SQLite database file. " * 64)
    connection = sqlite3.connect(path)  # the hook never fails a connection
    try:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("SELECT name FROM sqlite_master").fetchall()
    finally:
        connection.close()


def test_the_opt_out_leaves_sqlites_default_and_the_real_fsync(tmp_path: Path) -> None:
    assert ncf.installed(), "premise: the session hook is on"
    ncf.uninstall_no_commit_flush()
    try:
        assert getattr(sqlite3.connect, "__wrapped__", None) is None, "uninstall put the real connect back"
        assert ncf.install_no_commit_flush({ncf.OPT_OUT_ENV: "1"}) is False
        assert not ncf.installed()
        assert os.fsync is not ncf.no_fsync
        connection = sqlite3.connect(tmp_path / "durable.db")
        try:
            assert _level(connection) == _FULL
        finally:
            connection.close()
        assert ncf.install_no_commit_flush({ncf.OPT_OUT_ENV: "0"}) is True, "only the value 1 opts out"
        wrapped = sqlite3.connect
        assert ncf.install_no_commit_flush({}) is True
        assert sqlite3.connect is wrapped, "a second install does not wrap twice"
    finally:
        ncf.uninstall_no_commit_flush()
        ncf.install_no_commit_flush({})
    assert ncf.installed() and os.fsync is ncf.no_fsync
```

### 6.4 `tests/test_ad1315_protected_execution_authority.py`

**P3.** SEARCH:
```python
@pytest.mark.asyncio
async def test_start_fresh_database_creates_schema_v2(tmp_path: Path) -> None:
    layout, authority = await _started_authority(tmp_path)
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
```
REPLACE:
```python
class _KeptConnectionFactory:
    """Hands the authority a default connection and keeps it, so a test reads what the authority set on it."""

    def __init__(self) -> None:
        self.connection: Any = None

    async def connect(self, db_path: str) -> Any:
        self.connection = await default_factory.connect(db_path)
        return self.connection


@pytest.mark.asyncio
async def test_start_fresh_database_creates_schema_v2(tmp_path: Path) -> None:
    # BF-1006 (#1870): ``synchronous`` is per connection, so the authority's level is read on the connection the
    # authority set it on, before it stops. A connection the test opens reads only its own default (FULL in SQLite,
    # OFF under the test suite's no-flush hook), which is not what the authority set. ``user_version`` and
    # ``journal_mode=WAL`` belong to the file, so the test's own connection still reads those.
    layout = _make_layout(tmp_path)
    factory = _KeptConnectionFactory()
    authority = _authority(layout, connection_factory=factory)
    await authority.start()
    cursor = await factory.connection.execute("PRAGMA synchronous")
    synchronous = (await cursor.fetchone())[0]
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
```

**P4.** SEARCH:
```python
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = db.execute("PRAGMA synchronous").fetchone()[0]
        host = db.execute(
```
REPLACE:
```python
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
        host = db.execute(
```

The assertion `assert (version, journal, synchronous) == (2, "wal", 2)` (:353) stays byte-identical. Its `synchronous` is now the authority's own level.

### 6.5 `tests/fixtures/duration_scheduler.py`

**P5.** (A1: the SEARCH now starts at the base's :42, so the two older paragraphs are qualified in the same pair.) SEARCH:
```python
xdist. Comparing the collections, shutting down surplus workers, handing each
worker its first unit, the low-watermark top-ups, crash handling and every later
``schedule()`` stay xdist code.

The guarantee is order only, and it is stated as narrowly as it holds. For a run
that completes, every collected node runs exactly once, as with stock xdist, and
the canonical gate's collection-identity and exactly-once checks judge that run
unchanged. xdist's own crash handling is inherited as it is: it re-queues a
crashed worker's unit, so the crashing node is retried. Under ``--maxfail`` or
``-x`` (CI uses ``--maxfail=10``) the run stops early, and *which* nodes ran
before the stop depends on the order, as it does for any order change; the
scheduler stays enabled there.
```
REPLACE:
```python
xdist. Comparing the collections, shutting down surplus workers, handing each
worker its first unit, the low-watermark top-ups, crash handling and every later
``schedule()`` stay xdist code, with the one exception for a replacement worker
described below.

The guarantee is order only, and it is stated as narrowly as it holds, apart from
that exception. For a run that completes, every collected node runs exactly once,
as with stock xdist, and the canonical gate's collection-identity and exactly-once
checks judge that run unchanged. xdist's own crash handling is otherwise inherited
as it is: it re-queues a crashed worker's unit, so the crashing node is retried.
Under ``--maxfail`` or ``-x`` (CI uses ``--maxfail=10``) the run stops early, and
*which* nodes ran before the stop depends on the order, as it does for any order
change; the scheduler stays enabled there.

One change to crash handling (BF-1006, #1870). xdist lists a replacement worker
as soon as it is ready and registers its collection only when it has collected,
and both ``remove_node`` and every later ``schedule()`` reschedule every listed
worker. Stock xdist then pops a unit for a replacement that has not collected yet
and raises ``KeyError`` on its collection. From ``schedule()`` (another worker
finished collecting) the run aborts with exit 3. From ``remove_node`` (a second
worker was lost) ``DSession.worker_errordown`` swallows it, so the crashed test
is never reported and the popped unit is never sent. ``_assign_work_unit``
returns without taking a unit for such a worker; it gets work when it registers,
because ``DSession.worker_collectionfinish`` calls ``schedule()``.
```

**P6.** SEARCH:
```python
    def _assign_work_unit(self, node: WorkerController) -> None:
        if self._order_pending:
            self._order_pending = False
            self._apply_duration_order()
        super()._assign_work_unit(node)
```
REPLACE:
```python
    def _assign_work_unit(self, node: WorkerController) -> None:
        # BF-1006 (#1870): a replacement worker is listed before it has collected; it gets work when it registers.
        if node not in self.registered_collections:
            return
        if self._order_pending:
            self._order_pending = False
            self._apply_duration_order()
        super()._assign_work_unit(node)
```

### 6.6 `tests/test_ad1270f_duration_scheduler.py`

**P13 (S2).** SEARCH:
```python
    assert _scope(run.collection[survivor.sent[-1][0]]) == "tests/test_a.py", "the survivor pulls the head"
    assert len(run.config.lines) == 1


def test_the_rebuild_is_in_place_with_the_same_scope_keys_and_work_unit_objects() -> None:
```
REPLACE:
```python
    assert _scope(run.collection[survivor.sent[-1][0]]) == "tests/test_a.py", "the survivor pulls the head"
    assert len(run.config.lines) == 1


# --- BF-1006 (#1870): a replacement that has not collected yet gets no work until it registers ---

_SIX_FILES = {f"tests/test_{name}.py": 4 for name in "abcdef"}


def _after_one_death(make: Callable[[_Config], LoadFileScheduling]) -> tuple[_Run, _Node]:
    """Two workers each running one 4-test file; the first dies and its replacement is listed, still collecting."""
    run = _Run(make, _SIX_FILES)
    dead, _survivor = run.nodes
    assert run.scheduler.remove_node(dead) is not None, "premise: the dead worker had a test in flight"
    replacement = _Node("gw2", run.events)
    run.scheduler.add_node(replacement)
    return run, replacement


def _guarded_scheduler(config: _Config) -> LoadFileScheduling:
    return _ordered(config, _durations({scope: 1.0 for scope in _SIX_FILES}))


def test_a_second_death_while_the_replacement_collects_reports_the_crash_and_requeues_the_work() -> None:
    """Stock xdist raises KeyError here and DSession.worker_errordown swallows it: the second crashed test is never
    reported and the unit popped for the replacement is never sent. The subclass reports it and keeps every unit."""
    stock, _ = _after_one_death(_stock)
    with pytest.raises(KeyError):  # premise: stock xdist 3.8 hands the unregistered replacement a unit
        stock.scheduler.remove_node(stock.nodes[1])

    run, replacement = _after_one_death(_guarded_scheduler)
    survivor = run.nodes[1]
    in_flight = run.collection[survivor.sent[0][0]]
    assert run.scheduler.remove_node(survivor) == in_flight, "the lost worker's test is reported, so the run fails"
    assert replacement.sent == [] and run.scheduler.assigned_work[replacement] == {}
    assert len(run.scheduler.workqueue) == len(_SIX_FILES), "both dead workers' units are queued again"

    run.scheduler.add_node_collection(replacement, run.collection)
    run.scheduler.schedule()  # DSession.worker_collectionfinish does this once the replacement has collected
    assert replacement.sent, "the replacement gets work once it registers"
    run.nodes = [replacement]
    executed = run.run_to_completion()
    assert sorted(executed["gw2"]) == sorted(run.collection), "every test runs exactly once, on the replacement"


def test_a_schedule_while_a_replacement_collects_does_not_abort_the_run() -> None:
    """DSession.worker_collectionfinish calls schedule() whenever a worker has collected. Stock xdist then raises
    KeyError for a replacement still collecting, uncaught, and the run aborts with exit 3 (F-757)."""
    stock, _ = _after_one_death(_stock)
    with pytest.raises(KeyError):  # premise
        stock.scheduler.schedule()

    run, replacement = _after_one_death(_guarded_scheduler)
    run.scheduler.schedule()
    assert replacement.sent == [] and run.scheduler.assigned_work[replacement] == {}

    run.scheduler.add_node_collection(replacement, run.collection)
    run.scheduler.schedule()
    assert replacement.sent, "the replacement gets work once it registers"
    run.nodes = [run.nodes[1], replacement]
    executed = run.run_to_completion()
    assert sorted(sum(executed.values(), [])) == sorted(run.collection), "every test runs exactly once"


def test_the_rebuild_is_in_place_with_the_same_scope_keys_and_work_unit_objects() -> None:
```

**P14 (S2).** No other change in S2. `Callable` and `LoadFileScheduling` are already imported (:25, :33).

**P15 (S3).** SEARCH:
```python
        (directory / f"{worker}.json").write_text(json.dumps(payload), encoding="utf-8")
    return gate._validate_collection_manifests(
        directory,
        tmp_path / "run.collection.json",
        expected_workers=len(run.nodes),
        required_test_files=set(),
        junit_totals=gate.JUnitTotals(
            tests=len(collected), failures=0, errors=0, skipped=0, time_seconds=1.0
        ),
    )
```
REPLACE:
```python
        (directory / f"{worker}.json").write_text(json.dumps(payload), encoding="utf-8")
    # BF-1006 (#1870): the worker-exit log the wrapper's plugin writes in the controller, every worker finishing clean.
    exit_log = tmp_path / "run.workers.jsonl"
    exit_log.write_text(
        "".join(
            json.dumps({"event": "down", "worker": worker, "error": None, "exitstatus": 0}) + "\n"
            for worker in executed
        ),
        encoding="utf-8",
    )
    return gate._validate_collection_manifests(
        directory,
        tmp_path / "run.collection.json",
        expected_workers=len(run.nodes),
        required_test_files=set(),
        junit_totals=gate.JUnitTotals(
            tests=len(collected), failures=0, errors=0, skipped=0, time_seconds=1.0
        ),
        worker_exit_log=exit_log,
    )
```

**P16 (S3).** SEARCH:
```python
    assert totals.nodes == len(run.collection) == artifact["collection_count"]
    assert totals.workers == 4
```
REPLACE:
```python
    assert totals.nodes == len(run.collection) == artifact["collection_count"]
    assert totals.workers == 4
    assert totals.workers_lost == 0
```

### 6.7 `scripts/run_test_gate.py`

**P17.** SEARCH:
```python
_PYTEST_CONTROL_ENV = frozenset(
    {
        "PROBOS_GATE_COLLECTION_DIR",
        "PYTEST_ADDOPTS",
```
REPLACE:
```python
_PYTEST_CONTROL_ENV = frozenset(
    {
        "PROBOS_GATE_COLLECTION_DIR",
        "PROBOS_GATE_WORKER_EXIT_LOG",
        "PYTEST_ADDOPTS",
```

**P18.** SEARCH:
```python
    nodes: int
    workers: int
    sha256: str
```
REPLACE:
```python
    nodes: int
    workers: int
    sha256: str
    # BF-1006 (#1870): workers the worker-exit log shows going down with an error; a validated run has 0.
    workers_lost: int
```

**P19.** SEARCH:
```python
    # Report-only: the budget, or why there is none (see _compute_duration_budget).
    duration_budget: dict[str, object] | None = None
    duration_budget_skipped: str | None = None
```
REPLACE:
```python
    # Report-only: the budget, or why there is none (see _compute_duration_budget).
    duration_budget: dict[str, object] | None = None
    duration_budget_skipped: str | None = None
    # BF-1006 (#1870): the volume of the TEMP directory pytest inherits, and the worker-exit log, for every run.
    # A failed run has no receipt, and its triage starts from these.
    temp_volume: str | None = None
    worker_exit_log_path: str | None = None
```

**P20.** SEARCH:
```python
def _pytest_subprocess_env(
    repo_root: Path, collection_dir: Path
) -> dict[str, str]:
```
REPLACE:
```python
def _pytest_subprocess_env(
    repo_root: Path, collection_dir: Path, *, worker_exit_log: Path
) -> dict[str, str]:
```

**P21.** SEARCH:
```python
    env["PROBOS_GATE_COLLECTION_DIR"] = str(collection_dir.resolve())
    env["PYTHONPYCACHEPREFIX"] = str((collection_dir / "pycache").resolve())
    return env
```
REPLACE:
```python
    env["PROBOS_GATE_COLLECTION_DIR"] = str(collection_dir.resolve())
    env["PYTHONPYCACHEPREFIX"] = str((collection_dir / "pycache").resolve())
    env["PROBOS_GATE_WORKER_EXIT_LOG"] = str(worker_exit_log.resolve())
    return env
```

**P22.** SEARCH:
```python
def _validate_collection_manifests(
    collection_dir: Path,
    artifact_path: Path,
    *,
    expected_workers: int,
    required_test_files: set[str],
    junit_totals: JUnitTotals,
) -> CollectionTotals:
```
REPLACE:
```python
def _volume_of(directory: str) -> str:
    """BF-1006 (#1870): the volume ``directory`` is on.

    Its drive (``G:``) or UNC share on Windows, its mount point elsewhere. Only the
    volume is recorded, never the directory, which names the user.
    """
    absolute = os.path.abspath(directory)
    drive = os.path.splitdrive(absolute)[0]
    if drive:
        return drive.upper()
    current = absolute
    while not os.path.ismount(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current


def _count_lost_workers(path: Path, *, expected_workers: int) -> int:
    """BF-1006 (#1870): the xdist workers the worker-exit log shows going down with an error.

    ``scripts/_gate_pytest_plugin.py`` writes the log in the controller, one JSON object per
    line: ``ready``; ``down``, with xdist's ``error`` (``None`` for a clean finish) and the
    worker's own exit status when it finished; ``crash``, with the test it was running. Every
    expected worker must have gone down, so a log that lost records refuses the run instead of
    passing it. Every ``down`` record must carry ``error``, null or text, and only null is a
    clean exit: an empty text still counts the worker lost.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"pytest wrote no readable worker exit log: {path}: {exc}") from exc
    down: set[str] = set()
    lost = 0
    for number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"worker exit log line {number} is not JSON: {path}") from exc
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("event"), str)
            or not isinstance(record.get("worker"), str)
        ):
            raise RuntimeError(f"worker exit log line {number} is not a worker record: {path}")
        if record["event"] == "down":
            if "error" not in record or not (record["error"] is None or isinstance(record["error"], str)):
                raise RuntimeError(
                    f"worker exit log line {number} is a down record without a null or text error: {path}"
                )
            down.add(record["worker"])
            if record["error"] is not None:
                lost += 1
    missing = sorted({f"gw{index}" for index in range(expected_workers)} - down)
    if missing:
        raise RuntimeError("worker exit log has no exit for: " + ", ".join(missing[:8]))
    return lost


def _validate_collection_manifests(
    collection_dir: Path,
    artifact_path: Path,
    *,
    expected_workers: int,
    required_test_files: set[str],
    junit_totals: JUnitTotals,
    worker_exit_log: Path,
) -> CollectionTotals:
```

**P23.** SEARCH:
```python
    if junit_totals.tests != len(collected):
        raise RuntimeError(
            "pytest JUnit total does not match protected collection: "
            f"junit={junit_totals.tests} collected={len(collected)}"
        )
```
REPLACE:
```python
    if junit_totals.tests != len(collected):
        raise RuntimeError(
            "pytest JUnit total does not match protected collection: "
            f"junit={junit_totals.tests} collected={len(collected)}"
        )
    # BF-1006 (#1870): a worker can be lost after it wrote its manifest (no crash item, no
    # replacement manifest), so the controller's own record of every exit is checked too.
    workers_lost = _count_lost_workers(worker_exit_log, expected_workers=expected_workers)
    if workers_lost:
        raise RuntimeError(
            f"pytest lost {workers_lost} worker(s) during the run: see {worker_exit_log.name}"
        )
```

**P24.** SEARCH:
```python
    return CollectionTotals(
        nodes=len(collected),
        workers=expected_workers,
        sha256=collection_sha256,
    )
```
REPLACE:
```python
    return CollectionTotals(
        nodes=len(collected),
        workers=expected_workers,
        sha256=collection_sha256,
        workers_lost=workers_lost,
    )
```

**P25.** SEARCH:
```python
    if result.collection_totals is None or not collection_path.is_file():
        raise RuntimeError("Cannot issue a success receipt without collection evidence")
```
REPLACE:
```python
    if result.collection_totals is None or not collection_path.is_file():
        raise RuntimeError("Cannot issue a success receipt without collection evidence")
    if not result.temp_volume:
        raise RuntimeError("Cannot issue a success receipt without the TEMP volume")
```

**P26.** SEARCH:
```python
            "sha256": _sha256_file(collection_path),
            "totals": asdict(result.collection_totals),
        },
    }
```
REPLACE:
```python
            "sha256": _sha256_file(collection_path),
            "totals": asdict(result.collection_totals),
        },
        "run": {"temp_volume": result.temp_volume},
    }
```

**P27.** SEARCH:
```python
    collection_dir = junit_path.with_suffix(".collection-workers")
    collection_path = junit_path.with_suffix(".collection.json")
```
REPLACE:
```python
    collection_dir = junit_path.with_suffix(".collection-workers")
    collection_path = junit_path.with_suffix(".collection.json")
    worker_exit_log_path = junit_path.with_suffix(".workers.jsonl")
    # BF-1006 (#1870): the pytest child inherits this process's TEMP, TMP and TMPDIR (_subprocess_env),
    # so its temporary files land on this volume.
    temp_volume = _volume_of(tempfile.gettempdir())
```

**P28.** SEARCH:
```python
                                env=_pytest_subprocess_env(
                                    gate_root, collection_dir
                                ),
```
REPLACE:
```python
                                env=_pytest_subprocess_env(
                                    gate_root,
                                    collection_dir,
                                    worker_exit_log=worker_exit_log_path,
                                ),
```

**P29.** SEARCH:
```python
                                            junit_totals=junit_totals,
                                        )
                                    )
```
REPLACE:
```python
                                            junit_totals=junit_totals,
                                            worker_exit_log=worker_exit_log_path,
                                        )
                                    )
```

**P30.** SEARCH:
```python
            duration_budget=duration_budget,
            duration_budget_skipped=duration_budget_skipped,
        )
        _write_manifest(manifest_path, result)
```
REPLACE:
```python
            duration_budget=duration_budget,
            duration_budget_skipped=duration_budget_skipped,
            temp_volume=temp_volume,
            worker_exit_log_path=(
                str(worker_exit_log_path.relative_to(repo_root))
                if worker_exit_log_path.exists()
                else None
            ),
        )
        _write_manifest(manifest_path, result)
```

### 6.8 `scripts/_gate_pytest_plugin.py`

**P7.** SEARCH:
```python
    try:
        temporary.write_text(_render(payload), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
```
REPLACE:
```python
    try:
        temporary.write_text(_render(payload), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


# BF-1006 (#1870): the worker-exit log. The controller writes one JSON object per line to the
# file PROBOS_GATE_WORKER_EXIT_LOG names (the wrapper sets it; this plugin still adds no option):
# a worker's start, its exit with xdist's error (None for a clean finish) and its own exit status
# when it finished, and the test a worker was running when it was lost. xdist 3.8 gives the
# controller no operating-system exit code: a killed worker is "Not properly terminated".
# Measurement only, so a fault here -- reading xdist's objects, rendering the record or writing
# it -- drops that record and does not change the run: xdist calls pytest_testnodedown before its
# own crash guard. Each hook hands _write_worker_record a callable, so the reads run inside its
# guard. The guard catches Exception, not BaseException: a process-control exception
# (KeyboardInterrupt, SystemExit) still propagates, so an operator's cancellation is never
# swallowed. The wrapper refuses a run whose log is missing an exit.
_WORKER_EXIT_LOG_ENV = "PROBOS_GATE_WORKER_EXIT_LOG"
_ERROR_TEXT_LIMIT = 500


def _worker_name(node: object) -> str:
    try:
        return str(node.gateway.id)  # type: ignore[attr-defined]
    except Exception:
        return "unknown"


def _error_text(error: object) -> str | None:
    if error is None:
        return None
    try:
        return str(error)[:_ERROR_TEXT_LIMIT] or type(error).__name__
    except Exception:
        return "<unprintable>"


def _worker_exitstatus(node: object) -> int | None:
    output = getattr(node, "workeroutput", None)
    if not isinstance(output, dict):
        return None
    status = output.get("exitstatus")
    return status if type(status) is int else None


def _write_worker_record(build: Callable[[], dict[str, object]]) -> None:
    """Append the record ``build`` returns. ``build`` runs inside the guard: only a process-control exception escapes."""
    path = os.environ.get(_WORKER_EXIT_LOG_ENV)
    if not path:
        return
    try:
        record = {**build(), "wall": time.time()}
        line = json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return


@pytest.hookimpl(optionalhook=True)
def pytest_testnodeready(node: Any) -> None:
    _write_worker_record(lambda: {"event": "ready", "worker": _worker_name(node)})


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: object | None) -> None:
    _write_worker_record(
        lambda: {
            "event": "down",
            "worker": _worker_name(node),
            "error": _error_text(error),
            "exitstatus": _worker_exitstatus(node),
        }
    )


@pytest.hookimpl(optionalhook=True)
def pytest_handlecrashitem(crashitem: str, report: Any, sched: Any) -> None:
    # firstresult in xdist: returning None leaves the decision to the other implementations.
    _write_worker_record(
        lambda: {
            "event": "crash",
            "worker": _worker_name(getattr(report, "node", None)),
            "nodeid": str(crashitem),
        }
    )
```

`Callable` is already imported (`from typing import Any, Callable`, base :12), so P7 needs no import pair. No hook is wrapped in a decorator: pluggy reads each hook's argument names from its signature.

### 6.9 `scripts/wave-orchestrator.ps1`

**P8.** SEARCH:
```powershell
      $manifest.collection_path.Replace('\', '/') -ne $receipt.collection.path
    ) {
      throw "Canonical gate collection totals are absent or inconsistent"
    }
    return $receipt
```
REPLACE:
```powershell
      $manifest.collection_path.Replace('\', '/') -ne $receipt.collection.path
    ) {
      throw "Canonical gate collection totals are absent or inconsistent"
    }
    # BF-1006 (#1870): a success receipt states that no worker was lost and which volume TEMP was on.
    if (
      $collectionTotals.workers_lost -ne 0 -or
      $manifest.collection_totals.workers_lost -ne $collectionTotals.workers_lost
    ) {
      throw "Canonical gate lost a worker or does not record its lost workers"
    }
    $run = $receipt.run
    if (
      $null -eq $run -or
      -not ($run.temp_volume -is [string]) -or
      -not $run.temp_volume -or
      $manifest.temp_volume -ne $run.temp_volume
    ) {
      throw "Canonical gate receipt does not record its TEMP volume"
    }
    return $receipt
```

A missing `workers_lost` reads `$null`, and `$null -ne 0` is true, so a receipt without the field is refused.

### 6.10 `tests/test_run_test_gate.py`

**P9.** SEARCH:
```python
def _gate_stub_source(exit_code: int) -> str:
```
REPLACE:
```python
def _gate_stub_source(exit_code: int, *, defect: str = "") -> str:
```

**P10.** SEARCH:
```python
    return """from pathlib import Path
import hashlib
```
REPLACE:
```python
    return f"DEFECT = {defect!r}\n" + """from pathlib import Path
import hashlib
```

**P11.** SEARCH:
```python
collection_totals = {"nodes": 1, "workers": 1, "sha256": "fixture-nodes"}
```
REPLACE:
```python
collection_totals = {"nodes": 1, "workers": 1, "sha256": "fixture-nodes", "workers_lost": 0}
if DEFECT == "lost-worker":
    collection_totals["workers_lost"] = 1
```

**P12.** SEARCH:
```python
    "collection_totals": collection_totals,
}
manifest_path.write_text(json.dumps(manifest, sort_keys=True))
```
REPLACE:
```python
    "collection_totals": collection_totals,
    "temp_volume": "C:",
}
manifest_path.write_text(json.dumps(manifest, sort_keys=True))
```

**P33.** SEARCH:
```python
        "totals": collection_totals,
    },
}
receipt_path.write_text(json.dumps(receipt, sort_keys=True))
```
REPLACE:
```python
        "totals": collection_totals,
    },
    "run": {"temp_volume": "C:"},
}
if DEFECT == "no-run":
    del receipt["run"]
elif DEFECT == "other-volume":
    receipt["run"]["temp_volume"] = "Z:"
receipt_path.write_text(json.dumps(receipt, sort_keys=True))
```

**P34.** SEARCH:
```python
    else:
        assert "verify_build_receipt" not in state


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_rejects_zero_exit_without_gate_artifacts(
```
REPLACE:
```python
    else:
        assert "verify_build_receipt" not in state


_BF1006_REFUSALS = {
    "lost-worker": "lost a worker",
    "no-run": "TEMP volume",
    "other-volume": "TEMP volume",
}


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
@pytest.mark.parametrize("defect", sorted(_BF1006_REFUSALS))
def test_wave_orchestrator_verify_refuses_a_receipt_with_a_lost_worker_or_no_temp_volume(
    tmp_path: Path, defect: str
) -> None:
    """BF-1006 (#1870): the receipt validator checks the new fields; seeing them written is not enough."""
    repo = tmp_path / f"orchestrator-{defect}"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (scripts / "run_test_gate.py").write_text(
        _gate_stub_source(0, defect=defect), encoding="utf-8"
    )
    (prompts / "wave-plan.yaml").write_text(
        "waves:\n  - id: test-wave\n    kind: main\n    status: pending\n",
        encoding="utf-8",
    )
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {
                "current_wave": "test-wave",
                "current_stage": "verify_build",
                "history": [],
                "verify_build_receipt": {
                    "wave_id": "stale-wave",
                    "tree": {
                        "head": "stale",
                        "index_tree": "stale",
                        "status_sha256": "stale",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "/logs/\n/prompts/wave-orchestrator-state.json\n/scripts/gate-args.txt\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PROBOS_PYTHON"] = sys.executable

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "wave-orchestrator.ps1"),
            "verify",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )

    assert completed.returncode == 5, completed.stdout + completed.stderr
    assert "receipt validation failed" in completed.stderr
    assert _BF1006_REFUSALS[defect] in completed.stderr
    gate_arguments = (scripts / "gate-args.txt").read_text(encoding="utf-8")
    assert not Path(gate_arguments.split("--receipt ", 1)[1]).exists(), "a refused receipt is removed"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_rejects_zero_exit_without_gate_artifacts(
```

**P35.** SEARCH:
```python
        **_kwargs: object,
    ) -> object:
        artifact.write_text("{}\n", encoding="utf-8")
        return gate.CollectionTotals(nodes=2, workers=16, sha256="fixture")
```
REPLACE:
```python
        **_kwargs: object,
    ) -> object:
        artifact.write_text("{}\n", encoding="utf-8")
        return gate.CollectionTotals(nodes=2, workers=16, sha256="fixture", workers_lost=0)
```

**P36.** SEARCH:
```python
            raise RuntimeError("pytest collection evidence is incomplete")
        artifact.write_text("{}\n", encoding="utf-8")
        return gate.CollectionTotals(nodes=2, workers=16, sha256="fixture")
```
REPLACE:
```python
            raise RuntimeError("pytest collection evidence is incomplete")
        artifact.write_text("{}\n", encoding="utf-8")
        return gate.CollectionTotals(nodes=2, workers=16, sha256="fixture", workers_lost=0)
```

**P37.** SEARCH:
```python
    assert receipt["collection"]["totals"]["nodes"] == 1
    assert receipt["collection"]["totals"]["workers"] == 1
```
REPLACE:
```python
    assert receipt["collection"]["totals"]["nodes"] == 1
    assert receipt["collection"]["totals"]["workers"] == 1
    # BF-1006 (#1870): a real one-worker run through the wrapper's plugin. The controller wrote the worker-exit log,
    # the validation read it, and the receipt records no lost worker and the TEMP volume.
    assert receipt["collection"]["totals"]["workers_lost"] == 0
    assert receipt["run"] == {"temp_volume": gate._volume_of(gate.tempfile.gettempdir())}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["temp_volume"] == receipt["run"]["temp_volume"]
    exit_log = repo / manifest["worker_exit_log_path"]
    downs = [
        record
        for record in map(json.loads, exit_log.read_text(encoding="utf-8").splitlines())
        if record["event"] == "down"
    ]
    assert [(record["worker"], record["error"], record["exitstatus"]) for record in downs] == [
        ("gw0", None, 0)
    ]
```

**P38.** SEARCH:
```python
    "junit",
    "collection",
}
_CLEAN_RECEIPT_STATUS = {
```
REPLACE:
```python
    "junit",
    "collection",
    "run",  # BF-1006 (#1870): the TEMP volume
}
_CLEAN_RECEIPT_STATUS = {
```

**P39.** SEARCH:
```python
def test_gate_result_gains_two_trailing_optional_fields(gate: ModuleType) -> None:
    import dataclasses

    fields = dataclasses.fields(gate.GateResult)

    assert all(field.default is dataclasses.MISSING for field in fields[:-2])
    assert [field.name for field in fields[-2:]] == [
        "duration_budget",
        "duration_budget_skipped",
    ]
    assert [field.default for field in fields[-2:]] == [None, None]
```
REPLACE:
```python
def test_gate_result_ends_with_four_trailing_optional_fields(gate: ModuleType) -> None:
    """Formerly ``test_gate_result_gains_two_trailing_optional_fields``. BF-1006 (#1870) added ``temp_volume`` and
    ``worker_exit_log_path`` after the two duration-budget fields; every earlier field stays required."""
    import dataclasses

    fields = dataclasses.fields(gate.GateResult)

    assert all(field.default is dataclasses.MISSING for field in fields[:-4])
    assert [field.name for field in fields[-4:]] == [
        "duration_budget",
        "duration_budget_skipped",
        "temp_volume",
        "worker_exit_log_path",
    ]
    assert [field.default for field in fields[-4:]] == [None, None, None, None]
```

### 6.11a `tests/test_ad1299_s1a_repair_candidate.py`

**P40.** SEARCH:
```python
        collection_path=str(collection),
        collection_totals=gate.CollectionTotals(nodes=1, workers=1, sha256="0" * 64),
    )
```
REPLACE:
```python
        collection_path=str(collection),
        collection_totals=gate.CollectionTotals(nodes=1, workers=1, sha256="0" * 64, workers_lost=0),
        temp_volume="C:",
    )
```

### 6.11 New file `tests/test_bf1006_gate_worker_exit_log.py`

```python
"""BF-1006 (#1870): the gate's worker-exit log, its lost-worker count and the TEMP volume in the receipt.

The plugin half is driven with fake xdist nodes (A1: including attributes that raise and a record that cannot be
rendered) and then by a real ``pytest -n 2`` run whose worker is killed, so one test crosses the seam from xdist's
controller hooks to the wrapper's count. The wrapper half calls the wrapper's
helpers, as ``tests/test_run_test_gate.py`` does.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_test_gate.py"
PLUGIN = REPO_ROOT / "scripts" / "_gate_pytest_plugin.py"
EXIT_LOG_ENV = "PROBOS_GATE_WORKER_EXIT_LOG"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load("bf1006_run_test_gate", SCRIPT)


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load("bf1006_gate_pytest_plugin", PLUGIN)
    monkeypatch.setitem(sys.modules, "bf1006_gate_pytest_plugin", module)
    return module


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_log(path: Path, *records: dict[str, Any]) -> Path:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def _down(worker: str, error: str | None = None) -> dict[str, Any]:
    return {"event": "down", "worker": worker, "error": error, "exitstatus": 0 if error is None else None}


# --- The wrapper -------------------------------------------------------------------------------


def test_volume_of_names_the_drive_or_the_mount_point(gate: ModuleType, tmp_path: Path) -> None:
    if os.name == "nt":
        assert gate._volume_of(r"g:\gate-tmp-1\sub") == "G:"
        assert gate._volume_of(r"\\server\share\dir") == r"\\SERVER\SHARE"
    else:
        assert gate._volume_of("/") == "/"
        assert os.path.ismount(gate._volume_of(str(tmp_path)))
    assert str(tmp_path) not in gate._volume_of(str(tmp_path)), "the directory itself is never recorded"


def test_the_count_is_the_exits_with_an_error(gate: ModuleType, tmp_path: Path) -> None:
    clean = _write_log(
        tmp_path / "clean.jsonl",
        {"event": "ready", "worker": "gw0"},
        {"event": "ready", "worker": "gw1"},
        _down("gw0"),
        _down("gw1"),
    )
    assert gate._count_lost_workers(clean, expected_workers=2) == 0
    lost = _write_log(
        tmp_path / "lost.jsonl",
        {"event": "ready", "worker": "gw0"},
        {"event": "ready", "worker": "gw1"},
        _down("gw1", "Not properly terminated"),
        {"event": "crash", "worker": "gw1", "nodeid": "t/test_x.py::test_x"},
        {"event": "ready", "worker": "gw2"},
        _down("gw2"),
        _down("gw0"),
    )
    assert gate._count_lost_workers(lost, expected_workers=2) == 1


@pytest.mark.parametrize(
    ("lines", "match"),
    [
        (None, "no readable worker exit log"),
        ("not json\n", "is not JSON"),
        ("[1, 2]\n", "is not a worker record"),
        (json.dumps({"worker": "gw0"}) + "\n", "is not a worker record"),
        (json.dumps(_down("gw0")) + "\n", "no exit for: gw1"),
        # A2: each malformed gw0 record comes with a clean gw1 exit, so the log is complete and only the error
        # field can refuse it (without gw1 the completeness refusal answered first, a confound).
        (
            json.dumps({"event": "down", "worker": "gw0", "exitstatus": 0}) + "\n" + json.dumps(_down("gw1")) + "\n",
            "is a down record without a null or text error",
        ),
        (
            json.dumps({"event": "down", "worker": "gw0", "error": 1, "exitstatus": None})
            + "\n"
            + json.dumps(_down("gw1"))
            + "\n",
            "is a down record without a null or text error",
        ),
    ],
    ids=[
        "missing",
        "not-json",
        "not-an-object",
        "no-event",
        "an-expected-worker-never-exited",
        "down-without-error",
        "down-with-a-non-text-error",
    ],
)
def test_a_missing_malformed_or_incomplete_log_refuses_the_run(
    gate: ModuleType, tmp_path: Path, lines: str | None, match: str
) -> None:
    path = tmp_path / "workers.jsonl"
    if lines is not None:
        path.write_text(lines, encoding="utf-8")
    with pytest.raises(RuntimeError, match=match):
        gate._count_lost_workers(path, expected_workers=2)


def test_an_empty_error_text_still_counts_the_worker_lost(gate: ModuleType, tmp_path: Path) -> None:
    """Only a null error is a clean exit: an error rendered as an empty text is still an error."""
    log = _write_log(tmp_path / "empty.jsonl", _down("gw0"), _down("gw1", ""))
    assert gate._count_lost_workers(log, expected_workers=2) == 1


def _one_worker_manifest(gate: ModuleType, directory: Path, nodeids: list[str]) -> None:
    directory.mkdir()
    collected = sorted(nodeids)
    digest = gate._node_digest(collected)
    payload = {
        "schema_version": 1,
        "worker_id": "gw0",
        "exitstatus": 0,
        "collection_count": len(collected),
        "collection_sha256": digest,
        "final_count": len(collected),
        "final_sha256": digest,
        "removed_nodeids": [],
        "added_nodeids": [],
        "executed_nodeids": collected,
        "collected_nodeids": collected,
        "collected_files": sorted({nodeid.split("::", 1)[0] for nodeid in collected}),
    }
    (directory / "gw0.json").write_text(json.dumps(payload), encoding="utf-8")


def test_a_worker_lost_after_it_wrote_its_manifest_fails_the_validation(gate: ModuleType, tmp_path: Path) -> None:
    """The manifests alone pass: the worker wrote gw0.json and then died, so no replacement manifest and no crash item."""
    _one_worker_manifest(gate, tmp_path / "workers", ["tests/test_x.py::test_x"])
    arguments: dict[str, Any] = {
        "expected_workers": 1,
        "required_test_files": set(),
        "junit_totals": gate.JUnitTotals(tests=1, failures=0, errors=0, skipped=0, time_seconds=0.1),
    }
    clean = _write_log(tmp_path / "clean.jsonl", _down("gw0"))
    totals = gate._validate_collection_manifests(
        tmp_path / "workers", tmp_path / "clean.collection.json", worker_exit_log=clean, **arguments
    )
    assert (totals.workers, totals.workers_lost) == (1, 0), "premise: the same manifests pass with a clean log"
    lost = _write_log(tmp_path / "lost.jsonl", _down("gw0", "Not properly terminated"))
    with pytest.raises(RuntimeError, match=r"lost 1 worker\(s\)"):
        gate._validate_collection_manifests(
            tmp_path / "workers", tmp_path / "lost.collection.json", worker_exit_log=lost, **arguments
        )


def test_the_pytest_child_gets_the_exit_log_and_this_process_temp(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EXIT_LOG_ENV, "hostile")
    assert EXIT_LOG_ENV not in gate._subprocess_env(tmp_path), "an inherited value is cleared"
    env = gate._pytest_subprocess_env(tmp_path, tmp_path / "workers", worker_exit_log=tmp_path / "run.workers.jsonl")
    assert env[EXIT_LOG_ENV] == str((tmp_path / "run.workers.jsonl").resolve())
    for name in ("TMPDIR", "TEMP", "TMP"):  # the premise of recording the wrapper's own temp directory's volume
        assert env.get(name) == os.environ.get(name), name


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)


def _committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("/logs/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "-c", "user.name=ProbOS Tests", "-c", "user.email=tests@probos.invalid", "commit", "-q", "-m", "fixture")
    return repo


@pytest.mark.parametrize("temp_volume", ["G:", None, ""], ids=["recorded", "none", "empty"])
def test_a_success_receipt_carries_the_temp_volume_and_is_refused_without_one(
    gate: ModuleType, tmp_path: Path, temp_volume: str | None
) -> None:
    repo = _committed_repo(tmp_path)
    gates = repo / "logs" / "gates"
    gates.mkdir(parents=True)
    manifest, junit, collection = gates / "r.json", gates / "r.xml", gates / "r.collection.json"
    for path in (manifest, junit, collection):
        path.write_text("{}\n", encoding="utf-8")
    snapshot = gate._snapshot_tree(repo)
    result = gate.GateResult(
        label="r", started_at="2026-11-28T00:00:00Z", finished_at="2026-11-28T00:00:01Z",
        elapsed_seconds=1.0, wrapper_exit_code=0, preflight_exit_code=0, pytest_exit_code=0,
        preflight_only=False, interrupted=False, error="", tree_changed=False,
        snapshot_before=snapshot, snapshot_after=snapshot, command=["pytest"], phases=[],
        sanitized_pytest_environment=[], summary="", log_path="", junit_path=str(junit),
        junit_totals=gate.JUnitTotals(tests=1, failures=0, errors=0, skipped=0, time_seconds=0.1),
        collection_path=str(collection),
        collection_totals=gate.CollectionTotals(nodes=1, workers=1, sha256="0" * 64, workers_lost=0),
        temp_volume=temp_volume,
    )
    receipt = gates / "r.receipt.json"
    arguments = {"repo_root": repo, "result": result, "source_snapshot": snapshot,
                 "manifest_path": manifest, "junit_path": junit, "collection_path": collection}
    if not temp_volume:
        with pytest.raises(RuntimeError, match="TEMP volume"):
            gate._write_success_receipt(receipt, **arguments)
        assert not receipt.exists()
        return
    gate._write_success_receipt(receipt, **arguments)
    written = json.loads(receipt.read_text(encoding="utf-8"))
    assert written["run"] == {"temp_volume": "G:"}
    assert written["collection"]["totals"]["workers_lost"] == 0


# --- The plugin (the controller's hooks) ---------------------------------------------------------


def _node(name: str, **attributes: Any) -> SimpleNamespace:
    return SimpleNamespace(gateway=SimpleNamespace(id=name), **attributes)


def test_the_controller_hooks_write_one_record_per_event(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "workers.jsonl"
    monkeypatch.setenv(EXIT_LOG_ENV, str(log))
    clean, dead = _node("gw0", workeroutput={"exitstatus": 0}), _node("gw1")
    plugin.pytest_testnodeready(clean)
    plugin.pytest_testnodedown(clean, None)
    plugin.pytest_testnodedown(dead, "Not properly terminated")
    assert plugin.pytest_handlecrashitem(
        crashitem="t/test_x.py::test_x", report=SimpleNamespace(node=dead), sched=None
    ) is None, "firstresult: returning None leaves the crash to xdist"

    records = _records(log)
    assert all(isinstance(record.pop("wall"), float) for record in records)
    assert records == [
        {"event": "ready", "worker": "gw0"},
        {"event": "down", "worker": "gw0", "error": None, "exitstatus": 0},
        {"event": "down", "worker": "gw1", "error": "Not properly terminated", "exitstatus": None},
        {"event": "crash", "worker": "gw1", "nodeid": "t/test_x.py::test_x"},
    ]


def test_the_controller_hooks_contain_an_ordinary_fault_and_write_nothing_without_the_variable(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Unprintable(Exception):
        def __str__(self) -> str:
            raise ValueError("no text")

    monkeypatch.delenv(EXIT_LOG_ENV, raising=False)
    plugin.pytest_testnodedown(_node("gw0"), None)
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setenv(EXIT_LOG_ENV, str(tmp_path))  # a directory: the open fails, and the run goes on
    plugin.pytest_testnodedown(_node("gw0"), None)

    log = tmp_path / "workers.jsonl"
    monkeypatch.setenv(EXIT_LOG_ENV, str(log))
    plugin.pytest_testnodedown(object(), Unprintable())
    plugin.pytest_testnodedown(_node("gw3", workeroutput={"exitstatus": True}), "")
    first, second = _records(log)
    assert (first["worker"], first["error"], first["exitstatus"]) == ("unknown", "<unprintable>", None)
    assert (second["worker"], second["error"], second["exitstatus"]) == ("gw3", "str", None)
    assert math.isfinite(first["wall"])


class _Raises:
    """A data descriptor whose read raises ValueError, as a broken xdist attribute might (``getattr``'s default
    absorbs only AttributeError)."""

    def __get__(self, instance: object, owner: type | None = None) -> object:
        raise ValueError("this attribute cannot be read")


class _UnreadableOutput:
    gateway = SimpleNamespace(id="gw0")
    workeroutput = _Raises()


class _UnreadableGateway:
    gateway = _Raises()
    workeroutput = {"exitstatus": 0}


class _UnreadableNode:
    node = _Raises()


class _UnprintableItem:
    def __str__(self) -> str:
        raise ValueError("no text")


def _not_serializable(plugin: ModuleType, monkeypatch: pytest.MonkeyPatch) -> object:
    # The plugin fixture loads a fresh copy of the module per test, so only that copy's clock is replaced.
    monkeypatch.setattr(plugin, "time", SimpleNamespace(time=lambda: math.nan))
    return plugin.pytest_testnodeready(_node("gw0"))


_FAULTS: dict[str, tuple[Callable[[ModuleType, pytest.MonkeyPatch], object], list[dict[str, Any]]]] = {
    "workeroutput-raises": (lambda plugin, _: plugin.pytest_testnodedown(_UnreadableOutput(), None), []),
    "report-node-raises": (
        lambda plugin, _: plugin.pytest_handlecrashitem(
            crashitem="t/test_x.py::test_x", report=_UnreadableNode(), sched=None
        ),
        [],
    ),
    "crashitem-unprintable": (
        lambda plugin, _: plugin.pytest_handlecrashitem(
            crashitem=_UnprintableItem(), report=SimpleNamespace(node=_node("gw1")), sched=None
        ),
        [],
    ),
    "not-serializable": (_not_serializable, []),
    "gateway-raises": (
        lambda plugin, _: plugin.pytest_testnodedown(_UnreadableGateway(), None),
        [{"event": "down", "worker": "unknown", "error": None, "exitstatus": 0}],
    ),
}


@pytest.mark.parametrize("fault", list(_FAULTS))
def test_a_fault_while_building_or_writing_a_record_drops_only_that_record(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """xdist calls ``pytest_testnodedown`` before its own crash guard (``dsession.py``:240), so a hook that raised
    would change the run. A helper with its own fallback (``_worker_name``) still records; any other fault drops that
    one record, and the wrapper then refuses a run that is missing a ``down`` (``_count_lost_workers``)."""
    log = tmp_path / "workers.jsonl"
    monkeypatch.setenv(EXIT_LOG_ENV, str(log))
    call, expected = _FAULTS[fault]
    assert call(plugin, monkeypatch) is None, "the hook returned normally"
    records = _records(log) if log.exists() else []
    assert all(isinstance(record.pop("wall"), float) for record in records)
    assert records == expected


# --- The chain: a real xdist run, its controller's log, the wrapper's count ------------------------

_ALPHA = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"
# xdist requeues a crashed worker's unit, so the crashing test runs again on the replacement: it dies only the first
# time (a marker file beside it), or every replacement would die until xdist's restart limit.
_DIES = (
    "import os\nfrom pathlib import Path\n\n\ndef test_dies():\n"
    "    marker = Path(__file__).with_name('died-once')\n"
    "    if not marker.exists():\n"
    "        marker.write_text('1')\n"
    "        os._exit(1)\n"
)


@pytest.mark.parametrize(("dies", "lost"), [(False, 0), (True, 1)], ids=["clean", "a-worker-dies"])
def test_a_real_run_logs_each_exit_and_the_wrapper_counts_the_lost_worker(
    gate: ModuleType, tmp_path: Path, dies: bool, lost: int
) -> None:
    suite = tmp_path / "t"
    suite.mkdir()
    (suite / "test_alpha.py").write_text(_ALPHA, encoding="utf-8")
    (suite / "test_other.py").write_text(_DIES if dies else _ALPHA.replace("test_", "test_b_"), encoding="utf-8")
    log = tmp_path / "run.workers.jsonl"
    env = {name: value for name, value in os.environ.items() if not name.startswith(("PYTEST_", "COV_CORE", "COVERAGE"))}
    env.update({"PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1", EXIT_LOG_ENV: str(log)})
    env.pop("PROBOS_GATE_COLLECTION_DIR", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "t", "-q", "-p", "scripts._gate_pytest_plugin", "-n", "2",
         "--dist=loadfile", "-p", "no:randomly", "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == (1 if dies else 0), completed.stdout + completed.stderr

    records = _records(log)
    errors = [record for record in records if record["event"] == "down" and record["error"] is not None]
    crashes = [(record["worker"], record["nodeid"]) for record in records if record["event"] == "crash"]
    assert len(errors) == lost
    assert all(isinstance(record["error"], str) and record["error"] for record in errors)
    assert crashes == [(record["worker"], "t/test_other.py::test_dies") for record in errors]
    assert gate._count_lost_workers(log, expected_workers=2) == lost
```

### 6.12 `.github/agents/orchestrator.agent.md`

**P41.** SEARCH (the whole line 137):
```markdown
- **Gate workers (BF-981, #1815).** Run the broad gate at the wrapper's default of 16 workers (`--workers` in `scripts/run_test_gate.py`). A test that fails at 16 workers and passes at a lower count has no cause yet: find one from evidence (its failure text, the code it exercises, a reproduction under load) and treat it as a defect of the test (a premise that assumed an unloaded host, as BF-981 found for its family), of the product (a concurrency defect that load exposes) or of the environment (the host, its disk or another shared resource), then repair it or file it as that defect. Lowering the worker count never takes the place of that triage. A canonical gate run with a lower `--workers` value writes its receipt like any other run of the wrapper, and that receipt may advance a change only when a measured reason for the lower count is recorded in the gate report and in the owning issue. A rerun of selected tests outside the wrapper, serial or parallel, stays diagnostic (**Run broad gates through the canonical wrapper**).
```
REPLACE:
```markdown
- **Gate workers (BF-981, #1815; BF-1006, #1870).** Run the broad gate at the wrapper's default of 16 workers (`--workers` in `scripts/run_test_gate.py`). A test that fails at 16 workers and passes at a lower count has no cause yet: find one from evidence (its failure text, the code it exercises, a reproduction under load) and treat it as a defect of the test (a premise that assumed an unloaded host, as BF-981 found for its family), of the product (a concurrency defect that load exposes) or of the environment (the host, its disk or another shared resource, as BF-1006 found for synchronous writes), then repair it or file it as that defect. For a lost worker, start from the run's worker-exit log (`logs/gates/<stem>.workers.jsonl`, named in the manifest: each worker's exit, its error and the test it was running). Lowering the worker count never takes the place of that triage. A canonical gate run with a lower `--workers` value writes its receipt like any other run of the wrapper, and that receipt may advance a change only when a measured reason for the lower count is recorded in the gate report and in the owning issue; the lower counts to try are 12, then 8. A success receipt records its worker count, its lost workers (0, or the wrapper refuses it) and its TEMP volume; copy the count and the volume into the gate report. A rerun of selected tests outside the wrapper, serial or parallel, stays diagnostic (**Run broad gates through the canonical wrapper**).
```

### 6.13 `PROGRESS.md`

**P31.** SEARCH (the heading at build time; see section 4, Shared trackers):
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-1006 (2026-11-28), #1870 (F-757) -- test runs open SQLite with commit flushes off by default; the scheduler and the gate handle a lost worker.** At 16 workers the test volume completed about 600 synchronous writes per second however many workers asked, so a worker's boot-heavy first test spent about half of its 80-180 s inside SQLite commits at about 130 ms each, and pytest-timeout killed seven workers in one diagnostic run (with the flushes off: 0 lost, the same tests 28-36 s). A plugin module `tests/fixtures/no_commit_flush.py`, installed from `tests/conftest.py` for every pytest run (CI, focused runs, the gate), opens each `sqlite3` connection (aiosqlite included) at `synchronous=OFF` and makes `os.fsync` a no-op. Only the connection default changes: a store that sets its own level keeps it (the AD-1315 authority sets FULL and still flushes), a store that sets none (`ProfileStore`) runs at OFF, and a connection that finds its database locked keeps FULL. The PRAGMA runs with the busy timeout at 0 and restored, through `sqlite3.Connection.execute`, so a connect never waits on a lock, and the timeout is read on a cursor of the hook's own with no row factory, so a caller's row factory is neither called nor changed; a refusal logs one warning and never fails the connection. No test may assert a connection default, and `PROBOS_TEST_DURABLE_WRITES=1` opts a run out. `tests/test_ad1315_protected_execution_authority.py` now reads the authority's level on the authority's own connection. xdist rescheduled a replacement worker before it had collected, which aborted the run (exit 3) or lost the crash report; the duration scheduler now gives such a worker no work until it registers. The gate wrapper's plugin writes a worker-exit log from the controller (`logs/gates/<stem>.workers.jsonl`), the validation refuses a run that lost a worker or whose log is missing an exit, `CollectionTotals` gains `workers_lost`, every manifest records the TEMP volume and the success receipt gains `run.temp_volume`, all checked by `wave-orchestrator.ps1`'s receipt validator. The Gate workers standing order names the exit log, the receipt fields and the fallback counts (12, then 8, only on evidence). New `tests/test_bf1006_no_commit_flush.py` (16 tests) and `tests/test_bf1006_gate_worker_exit_log.py` (24 tests); 5 more in existing files. Contract `prompts/bf-1006-1870-test-runs-without-commit-flushes.md`.
```

### 6.14 `DECISIONS.md`

**P32.** SEARCH (the newest entry's heading at build time; at the base `4cf6fb5c` it is this one; see section 4, Shared trackers):
```markdown
### BF-930 -- A spoken reply buffers three sentences and holds off the idle full dream (2026-11-27, #1668)
```
REPLACE:
```markdown
### BF-1006 -- Test runs open SQLite with commit flushes off by default; the scheduler and the gate handle a lost worker (2026-11-28, #1870)

- *Scope.* #1870 (F-757). `tests/fixtures/no_commit_flush.py` (new) and `tests/conftest.py`; `tests/fixtures/duration_scheduler.py`; `scripts/run_test_gate.py`, `scripts/_gate_pytest_plugin.py`, `scripts/wave-orchestrator.ps1`; the Gate workers line of `.github/agents/orchestrator.agent.md`. No production code. Contract `prompts/bf-1006-1870-test-runs-without-commit-flushes.md`.
- *D1.* The cause of the lost workers was synchronous-write latency on the volume, not CPU, memory or the scanner (two 16-worker diagnostic runs on one head, 2026-11-28). The repair is in the test suite, not the wrapper, so CI, focused runs and the gate stay one environment: `PRAGMA synchronous=OFF` at connect only and `os.fsync` a no-op, with `PROBOS_TEST_DURABLE_WRITES=1` as the opt-out. Only the connection default changes: a store's own PRAGMA after connecting still wins (the AD-1315 authority keeps FULL), and a store that sets none runs at OFF. Rule: no test asserts a connection default; a test reads a store's level on the store's own connection.
- *D2.* The PRAGMA runs with the busy timeout at 0 and the caller's timeout put back, the three statements that set them through `sqlite3.Connection.execute`: `PRAGMA synchronous` reads the schema, so run plainly it waited out a locked database before the caller could bound the wait (Diff Reviewer round 1: 7.84 s against the doctor check's 2 s bound). The timeout is read on a base-class cursor of the hook's own (`sqlite3.Connection.cursor`) whose row factory is `None`, so a connection subclass's `execute` and `cursor` see none of the four statements and a caller's row factory (dict rows, a counter) is neither called nor changed (round 2). A failing PRAGMA, a locked database included, logs a warning and the connection is returned at SQLite's default; a failing warning is swallowed. The hook never fails a connection and never waits on a lock.
- *D3.* The scheduler gives a replacement worker no work until it has collected. Stock xdist raised `KeyError` from `schedule()` (uncaught: exit 3) and from `remove_node` (swallowed by `worker_errordown`, which lost the crash report and the popped unit). A lost worker still fails the run: its crash item is returned and reported.
- *D4.* The worker-exit log travels by environment variable, because the gate plugin adds no option. The wrapper requires a `down` record for every expected worker, each with an explicit `error` (null or text), and refuses any `down` whose error is not null, which also catches a worker lost after it wrote its manifest. The worker count stays `collection.totals.workers`; `workers_lost` and the TEMP volume are new; only the volume is recorded, never the directory.
- *Considered.* The CodebaseIndex memo (AD-1270f) works: one real build per worker; the boot herd at 16 workers remains and is the next suspect if 16 workers do not go green. Not done: the wrapper-only hook, a lower default worker count, TEMP on another volume, a `--worker-exit-log` option, receipt schema 2.
- *Reversal.* Revert the four commits. A receipt written after them carries `run` and `workers_lost`; a reader of schema 1 that reads named fields is unaffected.

### BF-930 -- A spoken reply buffers three sentences and holds off the idle full dream (2026-11-27, #1668)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| the hook (`tests/conftest.py`) | CI (`.github/workflows/ci.yml`:76-81, plain `pytest -n auto` with `scripts._ci_shard_pytest_plugin`) | active in every shard. The connection default changes to OFF and `os.fsync` is a no-op; a store's explicit level still wins (A2: the AD-1315 authority reads FULL, a captured real `ProfileStore` connection reads OFF). Same tests, same results |
| | focused runs (`pytest tests/...`) and the gate's pytest child (`run_test_gate.py`:1183-1200, `-I`, the repo's `tests/conftest.py`) | active. The opt-out passes through the gate unchanged, so the gate report says it was unset (section 8.4) |
| | the orchestrator's launcher that sets TEMP | unchanged. TEMP is now recorded as a volume in the manifest and the receipt |
| | tests run in a temporary root (`test_gate_timing.py`:150-186, `test_ad1270f_duration_scheduler.py`:1387, the new chain test) | no repo conftest, so no hook. Unchanged |
| | child processes a test starts (`python -m probos`, `multiprocessing` spawn) | not patched, so they still flush (section 13) |
| | `tests/fixtures/runtime_lifecycle.py`:182-203 (`SqliteTracker`, wraps `sqlite3.connect` per test) | wraps the hook's function and restores it afterwards. The hook sets no `factory`, so the tracker's `wants_default_factory` logic is unchanged |
| | `test_note_taker_save.py`:380 (`monkeypatch.setattr(os, "fsync", ...)`) | the test's patch wins, and monkeypatch restores the hook's no-op |
| | (A1) a consumer that connects to a store another connection holds and then sets its own busy timeout: `crew_enrollment_check.py`:43-47 and its test `test_bf906_doctor_check.py`:267-293 | the hook's PRAGMA fails at once, the caller's timeout is restored, one WARNING; the consumer's own `busy_timeout = 100` then bounds its read, as without the hook |
| | (A1) a connection subclass passed as `factory` (`runtime_lifecycle.py`:162 `_TrackedConnection`) | the hook's setting statements go through `sqlite3.Connection.execute` and its timeout read through a base-class cursor (A2), so the subclass sees none of them |
| | (A2) a connection subclass whose `__init__` sets a `row_factory` (dict rows, a counter), through `sqlite3.connect` or `aiosqlite.connect(..., factory=...)` | the hook reads the timeout on its own base-class cursor with no row factory: the caller's factory is not called during connect and is still the connection's |
| `PRAGMA synchronous` readers | `test_ad615_wardroom_db_hardening.py`:47; `test_ad1286_elastic_team_store.py`:846, :888-893 (probe reads after the store's PRAGMA; `statements` records only calls through the wrapper, :798-800, so the hook's raw PRAGMA is not in it); `test_ad1197_signed_envelopes.py`:2588 (a factory failing the store's own PRAGMA through its wrapper, :2360-2367) | read the store's own level, so they are unchanged |
| | `test_ad1315_protected_execution_authority.py`:311-353 | changed (P3, P4) |
| scheduler guard | `tests/conftest.py`:333-354, `make_duration_scheduler` | the scheduler is used only when the durations load. Otherwise stock xdist runs without the guard (section 13) |
| receipt (`run`, `collection.totals.workers_lost`) | `wave-orchestrator.ps1` `Read-GateSuccessReceipt` (:176-262, callers :294, :1134) | checks both (P8) |
| | `src/probos/cognitive/repair_candidate.py`:333-415 (`verify_gate_receipt`, schema 1) | reads named fields only, so the new fields bind through the evidence digest. Unchanged |
| | `tests/test_run_test_gate.py` `_RECEIPT_KEYS` (:2846-2855), used at :2964, :3114, :3221 | gains `run` (P38) |
| manifest (`temp_volume`, `worker_exit_log_path`, `collection_totals.workers_lost`) | `_gate_timing.py` (reads worker manifests, not the gate manifest); `scripts/gen_file_durations.py` | no reader of these keys. Unchanged |
| `_validate_collection_manifests(..., worker_exit_log=)` | `run_test_gate.py` main (P29); `test_ad1270f_duration_scheduler.py`:1181-1214 (P15); stubs at `test_run_test_gate.py`:923-933, :3042-3051 (`**_kwargs`) | every caller passes it, or the stub ignores it |
| `CollectionTotals(workers_lost=)` | constructors: `run_test_gate.py`:1371 (P24), `test_run_test_gate.py`:929, :3048 (P35, P36), `test_ad1299_s1a_repair_candidate.py`:163 (P40) | all updated |
| `GateResult` trailing fields | `test_run_test_gate.py`:3377-3387 | changed in place (P39) |
| gate plugin shape | `test_gate_timing.py`:481-495 (no `pytest_addoption`), :498-507 (no `raise` outside the collection guard) | the new functions add no option and contain no `raise` |
| Gate workers line | `CLAUDE.md`:24 (points to it by name); `tests/test_standing_orders_layout.py`:74 (section ownership), duplicate-sentence check | the name is unchanged, and the new sentences occur nowhere else |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts

- Count each SEARCH of section 6 at its turn: 1 each. The three new files do not exist.
- A/B on the base `4cf6fb5c`:
  - **S2:** P13 alone (without P6) leaves both new scheduler tests red, at the guarded `remove_node` and the guarded `schedule()` with `KeyError`. With P6, both pass.
  - **S1 and AD-1315:** with 6.1 and 6.2 but without P3 and P4, `test_start_fresh_database_creates_schema_v2` fails at :353 (`synchronous` 0). With P3 and P4 it passes. On the base it passes, which is the premise that the default is 2.
  - **Validator:** P9-P12, P33 and P34 without P8 leave the 3 items of the new ps1 test red (exit 0, not 5). With P8 they pass.
  - **Hook:** the new hook tests with 6.2 removed (the conftest hooks) are red at `ncf.installed()` (mutation H1).
  - **A1, locked store and dispatch:** with the round-1 hook (6.1 as built, staged tree `6be7f284`) in place of the amended 6.1, `tests/test_bf906_doctor_check.py::test_acm_store_held_by_an_exclusive_transaction_warns_within_the_busy_timeout` is red at its `elapsed < 2.0`, and in the amended `test_bf1006_no_commit_flush.py` the locked-database test is red at `elapsed < 1.0` and the base-class test red at `connection.seen == []`. With the amended 6.1 all three pass.
  - **A1, plugin and validator:** with the round-1 `_gate_pytest_plugin.py` block, the `workeroutput-raises`, `report-node-raises` and `crashitem-unprintable` items are red (ValueError out of the hook); with the round-1 `_count_lost_workers` and A2's fixtures (each with a clean `gw1` exit), `down-without-error` returns 0 and `down-with-a-non-text-error` returns 1, so both are red with no RuntimeError (A2: before the `gw1` record both stopped at the completeness refusal `no exit for: gw1`, which `match` rejected, a confound). With the amended P7 and P22 they pass.
  - **A2, row factory:** with the A1 hook (6.1 as built in staged tree `8617524e`) in place of the A2 6.1, the row-factory test `dict-rows` is red at `made == []` (`["row"]`; the hook then warned `KeyError: 0` and left the level at FULL), `tuple-rows` red at `made == []` (`["row"]`), and the aiosqlite row-factory test red at `made == []`. With the A2 6.1 all three pass, and the other 13 items of 6.3 pass under both.

### 8.2 Focused checks on the candidate

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf1006_no_commit_flush.py tests/test_bf1006_gate_worker_exit_log.py tests/test_ad1270f_duration_scheduler.py tests/test_run_test_gate.py tests/test_gate_timing.py tests/test_ad1299_s1a_repair_candidate.py tests/test_standing_orders_layout.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1315_protected_execution_authority.py tests/test_ad615_wardroom_db_hardening.py tests/test_ad1286_elastic_team_store.py tests/test_ad1197_signed_envelopes.py tests/test_note_taker_save.py tests/test_ci_shard_pytest_plugin.py tests/test_ci_shards.py tests/test_bf906_doctor_check.py -n 8 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_issue1419_failed_start_rollback.py tests/test_issue1452_stop_leftovers.py tests/test_ad1346_identity_service_boot.py tests/test_ad1346_admission_service_boot.py tests/test_ad1346_admission_shadow_boot.py tests/test_ad1270_working_memory_cognition.py tests/test_ad1240_workspace_result_lifecycle.py tests/test_ad1198_identity_continuity.py tests/test_ad1198_fork_resolution.py tests/test_runtime.py -n 8 -q
d:/ProbOS/.venv/Scripts/pytest.exe <every file of: git grep -l -E "sqlite3|aiosqlite" -- tests (184 at A1)> -n 8 -q
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-1006
```

Line 1 holds the changed slices. Line 2 holds every reader of a PRAGMA value, the fsync patcher, the CI shard plugin and (A1) the doctor check's locked-store test. Line 3 holds the `SqliteTracker` users and a booted runtime file. Line 4 (A1) is the sweep of every test file that touches `sqlite3` or `aiosqlite`, the class finding 1 belonged to; it is diagnostic, not the gate. Retriage a parallel failure at `-n 0`; a sweep failure that passes with `PROBOS_TEST_DURABLE_WRITES=1` and fails without it is a hard stop (section 5). Report the item counts. Expected new or changed items:
- `test_bf1006_no_commit_flush.py`: 16 (A2: the 2 row-factory items and the aiosqlite row-factory test added; 13 at A1; 9 before: `RefusesThePragma`'s test removed, the 2 genuine-refusal items, the locked-database, base-class and failing-handler tests added).
- `test_bf1006_gate_worker_exit_log.py`: 24 (A2: the same count; two fixtures gain a `gw1` record and one test is renamed; A1: 16 before, `down-without-error`, `down-with-a-non-text-error`, the empty-error test and 5 fault items added).
- `test_bf906_doctor_check.py`: unchanged; its locked-store test must pass.
- `test_ad1270f_duration_scheduler.py`: +2.
- `test_run_test_gate.py`: +3; P37 and P39 change in place.
- `test_ad1315`: 1 changed in place.

### 8.3 Mutation rows (one at a time on the candidate, the file restored byte for byte; one campaign of record)

Each locator is a whole stripped line of the candidate. Each occurs once in its file unless stated.

**A1 rerun scope.** Round 1's campaign (staged tree `6be7f284`: 19 of 22 killed, R2, P2m and V3 survived) stays of record for the rows whose file's executable lines A1 does not touch: G1-G3 (`duration_scheduler.py`: A1 changes only P5's docstring lines), R1 and R3-R7 (`run_test_gate.py`: A1 changes only `_count_lost_workers`, and these rows' lines and killers are untouched), V1-V3 (`wave-orchestrator.ps1` unchanged). Run on the A1 candidate: H1-H12 (H1 because `tests/conftest.py`'s docstring changed in P2, the rest because `no_commit_flush.py` is rewritten), R2, R8, R9, and P1m-P3m. Record each rerun file's sha256 beside the rows.

**A2 rerun scope.** The A1 campaign (staged tree `8617524e`; round 2 reported 28 Python rows killed) stays of record for every row except: H2-H16 (`no_commit_flush.py` changes; H13-H16 are new, H10b and H12 are re-located), and R8 and R9 (their killer fixtures change). H1 stays of record (`tests/conftest.py` is unchanged and its killers are byte-identical). P1m-P3m stay of record: A2 changes `_gate_pytest_plugin.py` in comment and docstring text only, and their killers are byte-identical (the renamed test is not one of them). G, R1-R7 and V rows are untouched.

| ID | File | Line (stripped) | Becomes | Killed by |
|---|---|---|---|---|
| H1 | `tests/conftest.py` | `install_no_commit_flush()` | `pass` | hook tests (premise `installed()`), bare, aiosqlite, fsync |
| H2 | `no_commit_flush.py` | `sqlite3.Connection.execute(connection, PRAGMA)` | `pass` | bare, store-level premise, aiosqlite, pass-through, base-class (level 2) |
| H3 | `no_commit_flush.py` | `sqlite3.Connection.execute(connection, PRAGMA)` | `sqlite3.Connection.execute(connection, PRAGMA) if __import__("threading").current_thread() is __import__("threading").main_thread() else None` | aiosqlite (connects in its own thread) |
| H4 | `no_commit_flush.py` | `if source.get(OPT_OUT_ENV) == "1":` | `if False:` | opt-out |
| H5 | `no_commit_flush.py` | `os.fsync = no_fsync` | `pass` | fsync, opt-out (final assertion) |
| H6 | `no_commit_flush.py` | `except Exception:` (in `connect`; the other is in `_warn_default_kept`) | `except ZeroDivisionError:` | both genuine-refusal items, the locked-database test, the not-a-database test (the SQLite error leaves `connect`) |
| H7 | `no_commit_flush.py` | `connection = real_connect(*args, **kwargs)` | `connection = real_connect(*args, **{k: v for k, v in kwargs.items() if k != "factory"})` | pass-through, base-class (`type(connection)`) |
| H8 | `no_commit_flush.py` | `sqlite3.Connection.execute(connection, "PRAGMA busy_timeout=0")` | `pass` | the locked-database test (the connect waits about twice its 2 s timeout: `elapsed < 1.0`) |
| H9 | `no_commit_flush.py` | `sqlite3.Connection.execute(connection, f"PRAGMA busy_timeout={prior}")` | `pass` | pass-through (1500 reads 0), base-class (1500), locked-database (2000), `inside-a-transaction` (5000) |
| H10 | `no_commit_flush.py` | `sqlite3.Connection.execute(connection, PRAGMA)` | `connection.execute(PRAGMA)` | base-class (`seen` not empty, level 2) |
| H10b | `no_commit_flush.py` | `prior = int(reader.execute("PRAGMA busy_timeout").fetchone()[0])` (A2 locator) | `prior = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])` | base-class (`seen` not empty; the interceptor's `SELECT 0` restores 0, not 1500); both row-factory items (`made == ["row"]`) |
| H11 | `no_commit_flush.py` | `except Exception:` (in `_warn_default_kept`) | `except ZeroDivisionError:` | failing-handler (RuntimeError out of `sqlite3.connect`) |
| H12 | `no_commit_flush.py` | the second `try:` and `finally:` of `_turn_off_commit_flush` (around `sqlite3.Connection.execute(connection, PRAGMA)`; A2 locator) | both lines deleted and the two lines between them dedented (the restore runs only after a PRAGMA that succeeded) | locked-database (busy timeout 0, not 2000), `inside-a-transaction` (0, not 5000) |
| H13 | `no_commit_flush.py` | `reader.row_factory = None` (A2) | `pass` | `dict-rows` (`made == ["row"]`, then `KeyError: 0`: one warning, level FULL), `tuple-rows` (`["row"]`), the aiosqlite row-factory test (`["row"]`) |
| H14 | `no_commit_flush.py` | `reader = sqlite3.Connection.cursor(connection)` (A2) | `reader = connection.cursor()` | both row-factory items (`made == ["cursor"]`: the subclass's override was called) |
| H15 | `no_commit_flush.py` | `prior = int(reader.execute("PRAGMA busy_timeout").fetchone()[0])` (A2) | `prior = int(sqlite3.Connection.execute(connection, "PRAGMA busy_timeout").fetchone()[0])` (the A1 line) | `dict-rows` (`["row"]`, warning, FULL), `tuple-rows` (`["row"]`), the aiosqlite row-factory test |
| H16 | `no_commit_flush.py` | `reader.close()` (A2) | `pass` | none expected: the cursor's only statement has been fetched and the cursor is released when the function returns. Record it as an equivalent survivor; the line stays as explicit cleanup |
| G1 | `duration_scheduler.py` | `if node not in self.registered_collections:` and the `return` after it | both lines deleted | both S2 tests (`KeyError`) |
| G2 | `duration_scheduler.py` | `if node not in self.registered_collections:` | `if node not in self.assigned_work:` | both S2 tests (`KeyError`) |
| G3 | `duration_scheduler.py` | `super()._assign_work_unit(node)` (the guard lines deleted) | `try:` / `super()._assign_work_unit(node)` / `except KeyError:` / `return` | the second-death test (`assigned_work[replacement] == {}`), the schedule test (same) |
| R1 | `run_test_gate.py` | `if workers_lost:` | `if False:` | the lost-after-manifest test |
| R2 | `run_test_gate.py` | `if record["error"] is not None:` | `if record["error"]:` | A1: `test_an_empty_error_text_still_counts_the_worker_lost` (1 counted, 0 under the mutant). Round 1 recorded it as equivalent; the reviewer's empty-name, empty-text error showed it is not |
| R8 | `run_test_gate.py` | `if "error" not in record or not (record["error"] is None or isinstance(record["error"], str)):` | `if False:` | malformed-log items `down-without-error` (`KeyError` from `record["error"] is not None`, which `pytest.raises(RuntimeError)` does not catch) and `down-with-a-non-text-error` (no refusal: with A2's clean `gw1` exit the count returns 1). Before A2 the second item stopped at the completeness refusal `no exit for: gw1`, which `match` rejected |
| R9 | `run_test_gate.py` | the same line | `if "error" not in record:` | malformed-log item `down-with-a-non-text-error` (no refusal: returns 1 with A2's `gw1` exit; before A2, the same completeness refusal) |
| R3 | `run_test_gate.py` | `if missing:` (in `_count_lost_workers`) | `if False:` | malformed-log item `an-expected-worker-never-exited` |
| R4 | `run_test_gate.py` | `"run": {"temp_volume": result.temp_volume},` | (line deleted) | `_RECEIPT_KEYS` tests (:2964, :3114, :3221), P37, the receipt test `recorded` |
| R5 | `run_test_gate.py` | `if not result.temp_volume:` | `if False:` | the receipt test `none` and `empty` |
| R6 | `run_test_gate.py` | `env["PROBOS_GATE_WORKER_EXIT_LOG"] = str(worker_exit_log.resolve())` | (line deleted) | child-env test; P37 (the validation finds no log, so the gate is red) |
| R7 | `run_test_gate.py` | `"PROBOS_GATE_WORKER_EXIT_LOG",` | (line deleted) | child-env test (inherited value not cleared) |
| P1m | `_gate_pytest_plugin.py` | `"error": _error_text(error),` | `"error": None,` | one-record-per-event test, real-run `a-worker-dies` |
| P2m | `_gate_pytest_plugin.py` | `except Exception:` (in `_write_worker_record`) / `return` | `except OSError:` / `return` | A1: fault items `not-serializable` (ValueError from `allow_nan=False`), `workeroutput-raises`, `report-node-raises`, `crashitem-unprintable`. Round 1 recorded it as equivalent; it is not |
| P3m | `_gate_pytest_plugin.py` | `record = {**build(), "wall": time.time()}` | the same line moved to just before `try:` (the reads run outside the guard) | fault items `workeroutput-raises`, `report-node-raises`, `crashitem-unprintable` (ValueError out of the hook) |
| V1 | `wave-orchestrator.ps1` | `$collectionTotals.workers_lost -ne 0 -or` | `$false -or` | ps1 item `lost-worker` |
| V2 | `wave-orchestrator.ps1` | `$manifest.temp_volume -ne $run.temp_volume` | `$false` | ps1 item `other-volume` |
| V3 | `wave-orchestrator.ps1` | `$null -eq $run -or` | `$false -or` | none expected: the next line also refuses a missing `run` (`$null -is [string]` is false). Record it as an equivalent survivor; the line stays as the explicit check |

### 8.4 The gate and acceptance runs

- One receipted broad gate on the committed candidate head: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-1006 --receipt logs/gates/bf-1006.receipt.json`, at the default 16 workers. Run it with `PROBOS_TEST_DURABLE_WRITES` unset, and say so in the gate report.
- This first canonical 16-worker run is also the full-run measurement. Acceptance run 2 follows on the same unchanged head: `--label bf-1006-r2 --receipt logs/gates/bf-1006-r2.receipt.json`.
- Report per run:
  - the wall time against the 3-worker baseline of 67.8-70.9 min;
  - seconds per test (0.207 before);
  - `collection.totals.workers`, `workers_lost` and `run.temp_volume`;
  - other load on the host.
- If 16 workers do not go green, triage from the worker-exit log as the Gate workers line requires. The next suspect is the boot herd.
- Run 12, then 8 workers only when no fix is in reach. The default becomes the highest count that goes green twice, and S4's line is revised with that measured reason. That is a new candidate head: re-review the delta, then run two fresh acceptance gates.

## 9. Diff Reviewer: properties to verify

The change claims that every pytest process opens SQLite connections at `synchronous=OFF` by default, without waiting on a lock, while each store's own level still wins. It also claims that the scheduler no longer aborts or hides a lost worker, and that the gate records and refuses a lost worker and records its TEMP volume. The consumers that must accept it are the stores' own PRAGMA tests, `wave-orchestrator.ps1`'s `Read-GateSuccessReceipt`, and `repair_candidate.verify_gate_receipt`.

1. The wrapper passes `*args` and `**kwargs` to the real `sqlite3.connect` untouched and sets no `factory`. On the new connection it reads the busy timeout (on the base-class cursor of item 1b), then sets it to 0, runs `PRAGMA synchronous=OFF` and restores what it read, in that order, those three through `sqlite3.Connection.execute` (never the instance's `execute`); the restore is in a `finally`, so the connection's busy timeout is unchanged afterwards even when the PRAGMA fails. It returns the connection on any exception after one WARNING, and an exception raised while delivering that WARNING does not escape (A1).
1b. (A2, round-2 finding 1.) The busy timeout is read on a cursor the hook makes with `sqlite3.Connection.cursor(connection)` and whose own `row_factory` is set to `None` before the read, closed in a `finally`. The hook never reads or assigns the connection's `row_factory`, never calls an instance's `cursor`, and fetches no row of its other three statements, so a caller's row factory is not called during connect.
1a. No connect through the hook waits on a lock: on a database another connection holds, the PRAGMA fails at once and the connection keeps SQLite's default level (A1, finding 1).
2. Install and uninstall are symmetric: idempotent install, and uninstall restores both originals. The opt-out reads exactly `"1"`, once, in `pytest_configure`.
3. No file under `src/probos` changes.
4. The guard is the first statement of `_assign_work_unit` and pops nothing. `remove_node` still returns the crash item. Every other line of `duration_scheduler.py` except the docstring lines of P5 is byte-identical.
5. `_count_lost_workers` refuses a missing, unreadable, malformed or incomplete log, and a `down` record whose `error` is missing or neither null nor text (A1). It counts every `down` record whose `error` is not null, `""` included. The validation raises when the count is not 0. The checks that already existed keep their order and their messages.
6. The new plugin functions contain no `raise`, and every read of an xdist object (`gateway`, `workeroutput`, `report.node`, `str(crashitem)`), the rendering and the write run inside `_write_worker_record`'s `try` (A1): each hook passes a callable, so an ordinary exception (`Exception` and its subclasses) from its arguments never leaves a hook. A2: a process-control exception (`BaseException` outside `Exception`: `KeyboardInterrupt`, `SystemExit`) does propagate, on purpose, so operator cancellation is never swallowed; no text claims otherwise. No hook is wrapped in a decorator. The plugin adds no option, and its existing hooks are byte-identical.
7. The receipt keeps `schema_version` 1 and every existing key, and gains only `run`. `collection.totals` gains only `workers_lost`. The manifest gains only `temp_volume` and `worker_exit_log_path`. No user directory is written to either.
8. The ps1 additions refuse a missing `workers_lost`, a non-zero one, a mismatch with the manifest, a missing `run`, an empty or non-string `temp_volume`, and a mismatch with the manifest.
9. P37 and P39 change tests in place with their reason inline. P3 and P4 keep the assertion line at :353 byte-identical. Nothing is deleted.
10. ASCII and LF in the new hand-written text. A2: regenerated generator output (the ledger pair, a config reference, a facade baseline) is exempt from the ASCII rule and must equal its generator's output, never a hand edit (`gen_ad_ledger.py --check` is the evidence). No file outside section 4 changes.
11. Each absolute word of the new text (each, every, no, only, never, none) holds against sections 1 and 7 and the Absence Verified list. In particular (A1, finding 6): no text claims that a run flushes no SQLite commit, or that every store sets its own level.

## 10. Verified Against Codebase (2026-11-28, base `4cf6fb5c47e071295c8342ae9e8d96c3cc3eb5bf`)

- `tests/conftest.py`:
  - imports at :27-32, and the AD-1270f memo fixture :128-140;
  - `install_abortive_self_pipe()` :64 (comment :61-63);
  - `pytest_sessionfinish` :305, `pytest_collection_modifyitems` :322, `pytest_xdist_make_scheduler` :333-354;
  - no `pytest_configure` or `pytest_unconfigure` in any conftest. The only other conftest is `tests/ablation/conftest.py`.
- `tests/fixtures/duration_scheduler.py`:
  - docstring :38-53 (the SEARCH of P5 is :52-53);
  - `class DurationOrderedLoadFileScheduling` :274;
  - `_assign_work_unit` :312-316;
  - `from xdist.scheduler import LoadFileScheduling` :96.
- xdist 3.8.0:
  - `scheduler/loadscope.py`: `registered_collections` :99, `nodes` :108-111, `collection_is_completed` :114-121, `add_node` :155-164, `remove_node` :166-205, `add_node_collection` :207-236, `_assign_work_unit` :263-282 (pop :268, read :275), `_reschedule` :313-336, `schedule` :338-355.
  - `dsession.py`: `worker_workerready` :172-191, `worker_workerfinished` :193-218 (`pytest_testnodedown(error=None)` :201, `workeroutput["exitstatus"]` :202), `worker_errordown` :238-267 (`except KeyError: pass` :242-245), `worker_collectionfinish` :274-306 (`schedule()` :306), `handle_crashitem` :432-452 (`rep.node = worker` :445).
  - `workermanage.py`: "Not properly terminated" :406-408, `self.workeroutput = kwargs["workeroutput"]` :420, errordown with excinfo :467.
  - `newhooks.py`: `pytest_testnodeready` :79, `pytest_testnodedown` :84, `pytest_handlecrashitem` firstresult :113-116.
- aiosqlite 0.22.1 (`__version__.py`:7): `core.py` `import sqlite3` :10; `connect` :443, whose `connector()` calls `sqlite3.connect(loc, **kwargs)` at :466, so the call resolves at call time.
- `src/probos/storage/sqlite_factory.py`: `import aiosqlite` :7, `connect` :18, `aiosqlite.connect(target, uri=read_only)` :37.
- `src/probos/execution/authority.py`: `self._db` :1438; `start` :1501-1513 (connect :1507, `PRAGMA synchronous = FULL` :1511).
- `tests/test_ad1315_protected_execution_authority.py`:
  - imports :9 (`sqlite3`), :15 (`Any`), :35 (`default_factory`);
  - `_authority(..., connection_factory=...)` :126-142, and `_started_authority` :182-189;
  - the test :311-354 (connect :315, `synchronous` :330, assertion :353);
  - `connection_factory=factory` precedent :1088.
- `tests/test_ad1270f_duration_scheduler.py`:
  - imports `Callable` :25, `LoadFileScheduling` :33;
  - `_Config` :61-101, `_Node` :104-121, `_durations` :132, `_ordered` :136, `_stock` :140, `_Run` :144-195 (`run_to_completion` :174-195);
  - crash-requeue test :468-491, rebuild test :494;
  - `_validate_with_the_wrapper` :1181-1214, pass test :1224-1237, drop test :1252-1265.
- `scripts/run_test_gate.py`:
  - `import tempfile` :20, `_PYTEST_CONTROL_ENV` :70-79;
  - `CollectionTotals` :150-156, `GateResult` :159-187;
  - `_subprocess_env` :812-822 (`os.environ.copy()`, no TEMP override), `_pytest_subprocess_env` :825-836;
  - `_build_full_command` :1157-1200, `_node_digest` :1232-1236;
  - `_validate_collection_manifests` :1239-1375 (worker ids :1247-1254, JUnit check :1345-1349, return :1371-1375);
  - `_write_success_receipt` :1641-1706 (collection refusal :1657-1658, payload :1663-1696);
  - `--workers` default 16 :1763;
  - `main`: collection paths :1785-1786, env call :1896-1898, validation call :1935-1945, GateResult :2035-2066, `_write_manifest` :2067.
- `scripts/_gate_pytest_plugin.py`: docstring `PYTEST_DONT_REWRITE` :1; imports `json` :6, `os` :8, `time` :9, `Any` :12; `pytest_sessionfinish` :189-222.
- `scripts/wave-orchestrator.ps1`: `Read-GateSuccessReceipt` :176-262; collection check :249-260; exit 5 on a refused receipt :1133-1144.
- `tests/test_run_test_gate.py`:
  - `_gate_stub_source` :115-197 (collection totals :144, manifest :146-156, receipt :165-196);
  - full-command test :217-240; env test :432-443; stubbed validation :923-933;
  - main receipt test :1386-1450;
  - verify test :2039-2155, next test :2158-2159;
  - `_RECEIPT_KEYS` :2846-2855; `_stub_gate` stubs :3031-3051;
  - receipt-key test :3186-3224; `GateResult` pin :3377-3387.
- `tests/test_ad1299_s1a_repair_candidate.py`: `_real_receipt` :138-175, `CollectionTotals` :163.
- `tests/test_gate_timing.py`: `_run_real_gate` :150-194, no-option test :481-495, no-raise test :498-507.
- `src/probos/cognitive/repair_candidate.py`: `_receipt_reason` :333-380 and `verify_gate_receipt` :383-415 (docstring: unread fields are not validated, :393-395).
- `.github/agents/orchestrator.agent.md`: the Gate workers line :137. `tests/test_standing_orders_layout.py`:74 maps the section to the orchestrator file.
- `PROGRESS.md`:1 `# ProbOS Progress`. `DECISIONS.md`:13 newest `### ` heading is BF-930's, and :23 is BF-1002's.
- `pyproject.toml`: `requires-python = ">=3.12"` :9, `timeout = 180` :190, `addopts = "-n 16 --dist=loadfile"` :196.

### Verified for Amendment A1 (2026-11-28, read at the base and in this worktree)

- `src/probos/doctor/checks/crew_enrollment_check.py`:43 `default_factory.connect(str(path), read_only=True)`, :47 `PRAGMA busy_timeout = ...` (after the connect).
- `tests/test_bf906_doctor_check.py`:267 the locked-store test, :279-281 `isolation_level=None` holder and `BEGIN EXCLUSIVE`, :290 `assert elapsed < 2.0`. It asserts the check's outcome and message (:288-289), not log records.
- `src/probos/crew_profile.py`:582-591 `_init_db`: `sqlite3.connect`, `CREATE TABLE`, `commit`; no `PRAGMA synchronous`.
- `src/probos/execution/authority.py`:1511 `PRAGMA synchronous = FULL`.
- Grep `PRAGMA synchronous` over `src/probos` (count mode): 25 files, one hit each.
- Base `tests/fixtures/duration_scheduler.py`:42-53 (`git show 4cf6fb5c:...`) is P5's new SEARCH, byte for byte.
- Base `scripts/_gate_pytest_plugin.py`:12 `from typing import Any, Callable`.
- `tests/test_gate_timing.py`:498-507: the no-raise test collects top-level functions containing an `ast.Raise`; the A1 plugin text has none.
- xdist `dsession.py`:238 `worker_errordown`, :240 `pytest_testnodedown(node=node, error=error)` before the `try` whose `except KeyError` is :244.
- From the orchestrator's probe (Windows, Python 3.12.13, SQLite 3.50.4), not re-run here: the plain PRAGMA on a held database took 1,087 ms at a 0.5 s timeout, read-only 1,094 ms; the bracket 31 ms, the busy timeout read back 500, and a later consumer `busy_timeout=100` honoured; a recording subclass does not see `sqlite3.Connection.execute(c, ...)`.

### Verified for Amendment A2 (2026-11-28 UTC, read in this worktree, staged tree `8617524e`)

- `tests/fixtures/no_commit_flush.py`:62 `prior = int(sqlite3.Connection.execute(connection, "PRAGMA busy_timeout").fetchone()[0])` (the line R2-1 names), :63 and :67 the bracket.
- CPython 3.12 `Modules/_sqlite/connection.c` (fetched): `pysqlite_connection_execute_impl` calls `pysqlite_connection_cursor_impl(self, NULL)` directly, not the Python-level `cursor`, and the cursor copies the connection's `row_factory` only when it is not `None`. So `sqlite3.Connection.execute` never calls a subclass's `cursor` (the row-factory test's `made` stays free of `"cursor"` for the hook's other statements), and setting the hook's cursor's `row_factory` to `None` after creation is what keeps the caller's factory out.
- aiosqlite 0.22.1 `core.py`:297-302 `row_factory` delegates to the sqlite3 connection; :443 `connect(database, *, iter_chunk_size=64, ...)`; :466 `sqlite3.connect(loc, **kwargs)`, so `factory=` and `timeout=` reach the hook.
- `scripts/run_test_gate.py`:1294 the error-field check, :1299 `record["error"] is not None` (R8's `KeyError`), :1301-1303 the completeness refusal after the loop (so a complete log reaches the error-field check first).
- `scripts/wave-orchestrator.ps1`:273 `$manifest.temp_volume -ne $run.temp_volume` (R2-6). `tests/fixtures/duration_scheduler.py`:324 `_assign_work_unit`, :326 the guard (R2-5). `tests/fixtures/runtime_lifecycle.py`:182-203 `install`/`uninstall`, :202 `sqlite3.connect = self._original` (R2-7). `tests/test_bf1006_gate_worker_exit_log.py`:45 and :47 the `plugin` fixture's parameter and `setitem` (R2-9).
- `scripts/_gate_pytest_plugin.py` P7 block: `_write_worker_record`'s guard is `except Exception:` (R2-8).

**Absence Verified (A1, 2026-11-28).** CLAIM: no test or `src` file opens a connection with `autocommit=False` (so the hook's refusal inside a transaction is reached only by the new tests). RUN: Grep `autocommit\s*=\s*False` over `src/**/*.py` and `tests/**/*.py`. FOUND: none (the round-1 candidate is staged in this worktree, and its tests do not use it). HOLDS: yes.

### Absence Verified (2026-11-28)

- **No test asserts a connection default other than AD-1315.**
  - RUN: Grep `synchronous` and Grep `SYNCHRONOUS|Synchronous=|fsync` over `tests/`.
  - FOUND: PRAGMA readers `test_ad615_wardroom_db_hardening.py`:47, `test_ad1286_elastic_team_store.py`:782/846/880/892, `test_ad1197_signed_envelopes.py`:2588, `test_ad1315_protected_execution_authority.py`:330/353. All other hits are prose about synchronous code.
  - HOLDS: each reader except AD-1315 reads the store's own connection after the store's PRAGMA (read :780-894 of AD-1286 and :2360-2367 of AD-1197).
- **Only one test patches `os.fsync`, and nothing binds `sqlite3.connect` or `os.fsync` at import.**
  - RUN: Grep `fsync` over `tests/`, then Grep `from sqlite3 import|=\s*sqlite3\.connect\s*$|from os import .*fsync|=\s*os\.fsync\s*$|sqlite3\.connect,|os\.fsync,` over `*.py`.
  - FOUND: `test_note_taker_save.py`:380 is the one `os.fsync` patch. The second search found `runtime_lifecycle.py`:185 (captured per test, after configure) and string literals in `test_ad1270b_architecture_fitness.py` and `check_architecture_principles.py`.
  - HOLDS: yes.
- **No sqlite3-level `Connection` subclass records statements.**
  - RUN: Grep `\(sqlite3\.Connection\)|factory=` over `src` and `tests`.
  - FOUND: `runtime_lifecycle.py`:162 (`_TrackedConnection`, no override).
  - HOLDS: yes. `set_trace_callback` is attached after connect (`test_ad1198_fork_resolution.py`:887, :1326).
- **The conftest imports open no database at import.**
  - RUN: Grep `sqlite3|aiosqlite` over `substrate/registry.py`, `substrate/spawner.py` and `config.py`.
  - FOUND: none.
  - HOLDS: yes.
- **No pin of the Gate workers line outside the orchestrator file.**
  - RUN: Grep `(?i)gate workers|workers lost|16 workers|--workers` over the agent profiles, `copilot-instructions.md`, `engineering-principles.md`, `architect-standards.md` and `test_standing_orders_layout.py`.
  - FOUND: `orchestrator.agent.md`:137 only. `CLAUDE.md`:24 names the section.
  - HOLDS: yes.
- **The gate plugin defines no `pytest_configure`, and no other conftest does.**
  - RUN: Grep `def pytest_configure|def pytest_unconfigure` over `tests` and `scripts`.
  - FOUND: `_ci_shard_pytest_plugin.py`:298, :343 only.
  - HOLDS: yes.
- **`_pytest_subprocess_env` and `CollectionTotals` have no callers or constructors beyond those listed.**
  - RUN: Grep `_pytest_subprocess_env\(`, then Grep `CollectionTotals\(|collection_totals` over `*.py` and `*.ps1`.
  - FOUND: main :1896 is the one caller. Constructors are at :1371, `test_run_test_gate.py`:929 and :3048, and `test_ad1299`:163.
  - HOLDS: yes.
- **No manifest-shape pin beyond `GateResult`'s trailing fields.**
  - RUN: Grep `set\(manifest\)|_MANIFEST_KEYS|fields\(gate\.GateResult|set\(totals\)|asdict\(` over the four gate test files.
  - FOUND: `test_run_test_gate.py`:3380.
  - HOLDS: yes.
- **BF-1006 is free.**
  - RUN: `gh search issues "BF-1006"` and Glob `prompts/bf-100*.md`.
  - FOUND: #1870 only, and prompts up to 1002 in this worktree.
  - HOLDS: yes, with the orchestrator's all-worktree enumeration (max 1004).

## 11. What this does NOT change

- Any `src/probos` store, its PRAGMAs, or production durability.
- `pyproject.toml` (`timeout = 180`, `-n 16 --dist=loadfile`) and the wrapper's `--workers` default.
- The receipt's schema version, and `repair_candidate.verify_gate_receipt`.
- The CodebaseIndex memo (AD-1270f) and the boot herd at 16 workers.
- Line 135 of `orchestrator.agent.md` ("roughly 15-19 minutes"). It is stale, but revise it only from the acceptance measurement.
- `docs/development/roadmap.md`. Its Bug Tracker has not been updated since BF-927, and recent contracts do not add rows.
- BF-932's tree and the speech worktrees.

## 12. Issue text (#1870, on merge)

```text
Shipped as BF-1006 (PR #<PR>, contract prompts/bf-1006-1870-test-runs-without-commit-flushes.md).
- Cause: synchronous-write latency on the test volume. At 16 workers the volume completed about 600 synchronous writes per second however many workers asked; a worker's first heavy test spent half its 80-180 s in SQLite commits (about 130 ms each) and pytest-timeout killed it. With the flushes off: 0 workers lost, the same tests 28-36 s.
- S1: tests/conftest.py installs tests/fixtures/no_commit_flush.py for every pytest run (CI, focused, gate): each sqlite3 connection (aiosqlite included) starts at synchronous=OFF and os.fsync is a no-op. Only the default changes: a store's own PRAGMA still wins (the AD-1315 authority keeps FULL), and a connection that finds its database locked keeps FULL; the PRAGMA runs with the busy timeout at 0 and restored, so no connect waits on a lock, and the timeout is read on the hook's own cursor with no row factory, so a caller's row factory is left alone. PROBOS_TEST_DURABLE_WRITES=1 opts out. Rule: no test asserts a connection default; the AD-1315 schema test now reads the authority's own connection.
- S2: the duration scheduler gives a replacement worker no work until it has collected. Stock xdist raised KeyError from schedule() (exit 3, the F-757 abort) and from remove_node (swallowed by worker_errordown, losing the crash report). A lost worker still fails the run.
- S3: the gate's plugin writes a worker-exit log from the controller (logs/gates/<stem>.workers.jsonl); the wrapper refuses a run that lost a worker or whose log misses an exit; collection.totals.workers_lost and run.temp_volume are in the receipt and checked by wave-orchestrator.ps1.
- S4: the Gate workers line names the exit log, the receipt fields and the fallback counts (12, then 8, only on evidence).
- Acceptance: two canonical 16-worker gates on the unchanged head: <wall times> against the 3-worker 67.8-70.9 min; workers lost 0; TEMP volume <volume>; <s/test>.
- Considered, deferred: CodebaseIndex (the AD-1270f memo works: 1 real build of 3.06 s per worker); the boot herd at 16 workers; child processes and ChromaDB still flush.
```

PR title: `Test-run SQLite connections start without commit flushes, and the gate survives and records a lost worker`.

## 13. Prior art and blind spots

- **Internal:**
  - BF-981 (#1815), which set the Gate workers line and the 16-worker default;
  - BF #466 and BF-657, the worker caps in `pyproject.toml` and CI;
  - AD-1270f, the duration scheduler and the CodebaseIndex memo;
  - AD-682, the per-worker data directories;
  - #1523, the five F-757 entries, and #1870's runs A and B;
  - `docs/development/test-suite-optimization-plan.md` P2.1, the worker sweep (still a measured step, unchanged).
- **External**, one source fetched (date used 2026-11-28):
  - SQLite's PRAGMA documentation (https://www.sqlite.org/pragma.html#pragma_synchronous): with `synchronous=OFF`, "If the application running SQLite crashes, the data will be safe, but the database might become corrupted if the operating system crashes or the computer loses power". Absorbed: it is the basis of D2.
  - Considered, deferred: PostgreSQL's "non-durable settings" practice for test databases. It is the same trade-off, and PostgreSQL is not used here.
  - No row of `docs/research/reference-projects.md` was examined, because this is test-harness plumbing.
- **Blind spots:**
  - Child processes a test starts (runtime children, `multiprocessing` spawn, `python -m probos`) and ChromaDB's own SQLite still flush. If the 16-worker gate still stalls, measure their share from the stack dumps first.
  - (A1, replaces round 1's unverified note.) `PRAGMA synchronous` reads the schema (SQLite's `PragFlg_NeedSchema`), so run plainly it waited out a locked database: Diff Reviewer round 1 measured 7.84 s for the doctor check's read against its 2 s bound. Now bounded: the PRAGMA runs at busy timeout 0 and fails at once. Two consequences are recorded, not repaired: a connection that opens while its database is locked stays at FULL for its life (it still works, only slower), and every such connect logs one WARNING (a test that locks a store on purpose sees it; section 8.2's sweep line checks that no such test counts warnings). A refusal for a file that is not a database or a connection opened inside a transaction is the same WARNING.
  - (A1.) Some stores set no level (`ProfileStore`, `crew_profile.py`:582-591), so in tests they run at OFF where production runs at FULL; some set FULL on purpose (the AD-1315 authority) and flush in tests too. Only 25 `src/probos` files set a level.
  - (A1.) A connection subclass's `execute` is not consulted for the hook's statements. A future subclass that relied on seeing every statement (a recorder) would not see them, which is the intent: they are not the caller's.
  - A test that kills a process and expects data on disk: the data is in the OS cache, so it survives, and readers see it.
  - A future store that relies on the connection default would read OFF in tests and FULL in production. The rule in D3 and the conftest docstring name this, and a store's tests must set and read the level on the store's connection.
  - When the durations file fails to load, the scheduler falls back to stock xdist, and the guard is absent there. The fallback prints a `disabled` line. Recorded, not repaired: a subclass of the stock class for the fallback would widen this slice.
  - The boot herd remains at 16 workers: 16 runtimes boot together, and collection takes about 3 minutes. It is the next suspect if acceptance fails.
  - The speech orchestrator's PR touches the same trackers (section 4, Shared trackers). BF-932's batch 1 is frozen elsewhere and is not touched.
  - (A2.) A process-control exception (`KeyboardInterrupt`, `SystemExit`) raised while a hook reads its arguments propagates out of the hook by design (section 9 item 6).
- **Recorded follow-ups (A2, Diff Reviewer round 2; not repaired here; for the wave's follow-up issue):**

| ID | Severity, reach | Defect | Smallest fix |
|---|---|---|---|
| R2-5 | P2, injected-only (introduced by S2) | A replacement worker whose collection xdist's `add_node_collection` rejects (it logs the mismatch and returns without registering it) is treated by the S2 guard (`duration_scheduler.py`:326) as still collecting, so its queued work is never assigned: the reviewer's two-worker probe did not finish within 8 s (queue 1, no assignment), where stock xdist aborts with exit 3. Reaching it needs a replacement whose collection differs from the official one; the gate's collection is deterministic and its identity validated | Override `add_node_collection`, remember a node still unregistered after `super()` returns, and let stock behaviour (the mismatch failure) run for it instead of the guard |
| R2-6 | P2, injected-only | `wave-orchestrator.ps1`:273 compares the manifest's and the receipt's TEMP volume with `-ne`, which is case-insensitive, so `/mnt/Build` equals `/mnt/build`. Both values come from one `_volume_of` call in one run, so only tampering reaches it | `-cne`, plus a ps1 test id for a case-only difference |
| R2-7 | P2, injected-only (a leaked tracker at session end) | If `uninstall_no_commit_flush()` runs while a `SqliteTracker` (`runtime_lifecycle.py`:162-203) still wraps `sqlite3.connect`, the tracker's later `uninstall` (:202) restores the hook's wrapper: `installed()` is False, yet new connections read `synchronous=0` and the durable opt-out is defeated | Enforce LIFO ownership: `uninstall_no_commit_flush` restores the globals only while `sqlite3.connect` is still the hook's own wrapper, and otherwise reports the out-of-order teardown |
| R2-9 | P3, size, ordinary reach | `test_bf1006_gate_worker_exit_log.py` `plugin` fixture: the `monkeypatch.setitem(sys.modules, ...)` line (:47) and its `monkeypatch` parameter (:45) are redundant, because `_load` already installs the module and `MonkeyPatch.undo()` keeps the new entry | Delete both lines' redundant parts (the `setitem` line and the parameter) |

## 14. Acceptance criteria

1. The A/B of 8.1 holds. The mutation rows of 8.3 are killed as stated, with any expected survivors recorded as equivalent.
2. The focused checks of 8.2 pass, and the pre-existing tests in those files pass unchanged except the in-place changes named in 6.
3. `git diff --check` is clean, the new hand-written text is ASCII (regenerated generator output exempt, A2), and no file outside section 4 changes.
4. The Diff Reviewer approves against section 9.
5. Two canonical 16-worker gates on the unchanged committed head are green. Each receipt shows `collection.totals.workers` 16, `workers_lost` 0 and a `run.temp_volume`. The wall times and seconds per test are reported against the 3-worker baseline (8.4). The fallback ladder is used only on evidence.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
