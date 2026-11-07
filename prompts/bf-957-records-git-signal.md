# BF-957 (#1760): Ship's Records says when git fails, and `probos doctor` reports a stopped records history

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06
**Status:** ready to build after AD-1358 S1 (#1750) is on `main`.
**Base:** `baea653d` (origin/main `48ed13bf` with BF-952, plus AD-1358 S1). AD-1358 S1 touches none of this contract's source files.
**Dependencies:** none.
**Tier:** M1 STANDARD (tests only). M2 HIGH (data integrity: git handling of the records repository, plus a new subprocess site). M3 STANDARD (trackers).
**Estimated tests:** one new file, `tests/test_bf957_records_git_signal.py`, with 22 functions and 36 cases after Amendment A3 (18 and 29 before it). Five existing test or fixture files are edited. Counted by reading, not by running.
**BF number:** BF-957, held by #1760. Nothing new is allocated.

**Which text describes the head.** Before building, run `git diff --stat baea653d HEAD -- src/probos/knowledge/records_store.py src/probos/doctor/ src/probos/config_models/knowledge.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1270e1_config_facade.py tests/test_bf892_spawn_env_guard.py tests/fixtures/ad1346_effect_census.py`. Any change there is a hard stop: the SEARCH text goes back to the Architect. Working copies are CRLF; SEARCH text here is LF. Where prose and a block differ, the block wins.

## 1. Problem

1. `RecordsStore._git_sync` (`records_store.py:1624-1637`) logs the stderr of a non-zero git exit at DEBUG (`:1636`) and returns stdout. `_commit` (`:1639-1647`) catches any exception and logs it at DEBUG (`:1647`). A stale `.git/index.lock` makes every `git add` and `git commit` fail. Records are still written to disk, but the history stops, and nothing is logged above DEBUG.
2. The issue's line numbers were read on `c6f342d8`; BF-952 has since moved them by about +310:

| Issue | Now |
|---|---|
| `_git_sync` :1314-1327 | :1624-1637 |
| `_commit` :1329-1337 | :1639-1647 |
| readers :1067, :1182 | :1379, :1492 |
| `write_entry` :362 | :674 |
| `append_captains_log` :481 | :793 |
| `write_bill` :583 | :895 |
| `publish` :1105 | :1417 |
| `write_workspace_file` :1234 | :1544 |
| `append_workspace_file` :1259 | :1569 |

3. **Premise correction.** "The other 12 call sites rely on it not raising" is only partly right. `_git_sync` does not raise on a non-zero exit. It does raise `TimeoutExpired` after the kill, and `FileNotFoundError`/`OSError` when git is missing. Only `_commit` (`:1644-1647`), `get_history` (`:1378/1395`) and `get_stats` (`:1491/1494`) catch these. The six `git add` sites pass them to their callers. This contract keeps both behaviours exactly.
4. Only `git commit` is serialized: by `_commit_lock`, an `asyncio.Lock` (`:521`, `:1643`). Every `_git` call runs on a default-executor thread (`:1622`). So one write's `git add` can run while another write's `git add` or `git commit` is running. The command that loses exits 128 with git's lock message, and its path is never staged, so it stays out of the history until the same path is written again.

### The 14 call sites, and what each reads from `_git_sync`

| # | Line | Verb | Return value read? | On an exception today |
|---|---|---|---|---|
| 1-5 | 542, 544, 545, 548, 549 | init, config ×2, add, commit (`initialize`) | no | propagates to `cognitive_services.py:617` (records disabled for the run) |
| 6 | 675 | add (`write_entry`) | no | propagates |
| 7 | 794 | add (`append_captains_log`) | no | propagates |
| 8 | 896 | add (`write_bill`) | no | propagates |
| 9 | 1379 | log (`get_history`) | **stdout, parsed** | caught; returns `[]` |
| 10 | 1418 | add (`publish`) | no | propagates |
| 11 | 1492 | rev-list (`get_stats`) | **stdout, `int()`** | caught; count 0 |
| 12 | 1545 | add (`write_workspace_file`) | no | propagates |
| 13 | 1570 | add (`append_workspace_file`) | no | propagates |
| 14 | 1645 | commit (`_commit`) | no | caught (now WARNING) |

After this change `_git_sync` returns `result.stdout` on every path that does not raise, and raises the same exception objects. The lock delays a call; it does not change what the call returns. So the change is invisible to all 14 sites. Test T9 pins this. (A4 narrows this: git's output is decoded as UTF-8, so on a host whose locale codec is not UTF-8 a read returns git's text where the base returned `None` or misread text; §7.2c, T13.)

## 2. Solution

1. **Store (`records_store.py`).**
   - A per-store `threading.Lock` held around the child's whole life.
   - `_warn_git_once` and `_forget_git_warnings` hold the once-per-error memory.
   - `_git_error_line` defines what makes two errors the same.
   - A timeout is logged at WARNING, then re-raised.
   - `_commit` logs at WARNING under the same rule.
2. **Doctor check (`doctor/checks/records_git_check.py`, new).** Registered after `disk`.
3. **Config (`config_models/knowledge.py`).** Three fields on `RecordsConfig`, each with a bound and a description: `git_lock_stale_minutes` 10.0, `git_uncommitted_warn_paths` 50, `git_last_commit_warn_hours` 24.0.
4. **Guard tables.** BF-892's `TRUSTED_ENV_SITES` and AD-1346's `SUBPROCESS_SITES` each gain one row for the doctor's git launch.
5. **Generated documents.** `config-facade-baseline.yaml` and `config-reference.md`, regenerated by their own tools.

## 3. Decisions

### 3.1 Root cause (D1, D2): the code cannot pick it

What can cut off a git child, or run two at once:

| Way | What the code proves | What it does not prove |
|---|---|---|
| **Timeout kill.** `subprocess.run(..., timeout=30)` at `:1626-1633` | On `TimeoutExpired`, `run()` calls `process.kill()`, reaps the child and re-raises. `kill()` is `TerminateProcess` on Windows and `SIGKILL` on POSIX. Neither lets git run its lockfile cleanup (atexit and catchable signals). `git add` and `git commit` both create `index.lock` empty and fill it at the end, so a kill partway leaves a **0-byte** lock. | Whether a 30 s timeout ever fired. On Windows, `git` may resolve to the Git for Windows launcher; whether killing the launcher also stops the real `git.exe` cannot be decided from this repository. |
| **Vessel shutdown** while a sync is in flight | A graceful `asyncio.run` exit joins the default executor, so it waits for the child. `RecordsStore` has no close or flush hook. | How the vessel was stopped. A hard kill of a process tree, or of a console that delivers an uncatchable stop to the child, leaves a lock; a hard kill of Python alone orphans git, which then finishes and cleans up. |
| **Overlap of two `_git_sync` calls** | It happens. `_commit_lock` covers only `:1645`. The adds at 675, 794, 896, 1418, 1545 and 1570, and the reads at 1379 and 1492, take no lock and run on `run_in_executor(None, ...)` threads. One store in production (`cognitive_services.py:609`). The CLI instances (`__main__.py:3285`, `:3574`) only read and run in other processes. | That overlap leaves a lock. **It does not**: the loser fails at `O_EXCL` without ever creating the file, and the winner removes its own. Overlap loses individual paths from the history; it does not stop the history. |

So the evidence in the repository cannot choose between (a) and (b). **The change taken (D2, option 1):**
- **Serialize the store's git children.** This fixes the overlap defect the code does prove. It also means that, from here on, git's "Unable to create … index.lock: File exists" message in this log comes from an outside holder or a stale lock, not from the store contending with itself.
- **Log the timeout kill at WARNING before re-raising.** The next time a lock is left behind, the log says whether the timeout caused it, which is the evidence that would choose option 2.

The 30 s value is unchanged (L1).

### 3.2 Signal (D3)

- **Where the memory lives.** On the store instance: `_git_warned: dict[tuple[str, str], None]`, in insertion order, read and written only under `_git_warned_lock` (a `threading.Lock` held only for dictionary operations).
- **Bound.** `_GIT_WARNED_MAX = 32`. When full, the oldest key is dropped before the new one is added.
- **What makes two errors the same.**
  - Non-zero exit: the key is `(verb, first non-empty line of stderr, else of stdout, cut to 300 characters)`. The lock message carries the repository path, not the record's path, so every `git add` blocked by one lock shares one key. A pathspec error carries its path, so each distinct path is a distinct error.
  - Timeout: the key is `(verb, "timeout")`.
  - `_commit` exception: the key is `("commit", exception type name)`.
- **Reset.** A zero exit of `add` or `commit` (`_GIT_INDEX_VERBS`) clears the memory. A successful read (`log`, `rev-list`) does not, because reads succeed while a lock remains.
- **Exemption.** A non-zero exit whose stdout contains "nothing to commit" or "nothing added to commit" is not an error. The second phrase is git's wording when untracked files are present. On the base it was silent only because its stderr was empty.
- **Unchanged.** The return value, and whether and what `_git_sync` and `_commit` raise.

### 3.3 Doctor check (D4)

- **Registration.** `register_check` (`doctor/registry.py:21-33`) runs as an import side effect of `doctor/checks/__init__.py:9-35`. The new module goes after `disk_check`; no positional test pins the neighbours of `disk`. Pinned neighbours (`extras`→`verifier_independence`, `crew_enrollment`→`token_accounting`→`role_templates`) are untouched.
- **Repository path.** `resolve_records_repo_path(ctx.config.records, ctx.data_dir)` (`config.py:2658-2666`), the resolver startup uses (`cognitive_services.py:602-608`). Tests pass `repo_path` explicitly and a temporary `data_dir`.
- **Read-only.**
  - The lock: `Path.stat()` only.
  - Git: `git -C <repo> status --porcelain --untracked-files=all --no-renames -z` and `git log -1 --format=%ct`, with `env={**trusted_command_env(), "GIT_OPTIONAL_LOCKS": "0"}` and a 15 s timeout. With optional locks off, `git status` does not refresh the index, so stopping it at the timeout holds no lock. A3: both commands also start with `HARDENED_GIT_CONFIG_ARGS` (`execution/command_env.py:70`: `core.hooksPath` set to the null device, `core.fsmonitor=false`), because optional locks do not stop a configured fsmonitor, which runs at `git status` and may write in the repository.
  - Nothing in the module writes, renames or deletes.
- **Behaviour by case:**

| Case | Outcome |
|---|---|
| Config not loaded | WARN, "not checked" |
| `records.enabled` false | OK |
| `auto_commit` false | OK, "ProbOS keeps no records history" (the lock is not read) |
| Path exists and is not a directory (A3) | FAIL, "is not a directory": startup's `mkdir` refuses it and records are disabled |
| Directory missing | OK, "created when the vessel starts" |
| No `.git` directory | WARN |
| `git` not on PATH | lock still reported; WARN line for the parts that need git |
| No commit yet | WARN, "last commit: not read (exit 128: …)" |
| Lock age ≥ `git_lock_stale_minutes` | FAIL |
| Lock age under the threshold | OK, "a git command may be running" |
| Uncommitted paths > `git_uncommitted_warn_paths` | WARN |
| Last commit age ≥ `git_last_commit_warn_hours` **and** ≥1 uncommitted path | WARN (an idle vessel with a clean tree is not flagged) |

  The overall outcome is the worst part. `detail` holds one line per part.
- **Config.** Pydantic fields with `gt`/`ge` bounds, documented by `Field(description=...)`, which `scripts/gen_config_reference.py:164` renders. The config tests that enumerate fields are edited (P2-10 to P2-12), and the baseline is regenerated (R1).

### 3.4 Operator text (D5)

- **Log.** (A3: the message carries git's first non-empty output line only, the line that keys the error. Git's further text, which for a lock says to remove the file without the backup precondition, is not logged. A timeout says what the command changed is not known.) "Ship's Records: git add failed (exit 128): fatal: Unable to create '…/index.lock': File exists. … Records are still written to disk, but a failed add or commit leaves them out of the records history. This error is logged once until a git add or commit succeeds; `probos doctor` reports the repository's state."
- **Doctor remediation.** "A git process that ended without cleaning up leaves <lock>. With the vessel stopped and no git process using <repo>, back up <git_dir>; removing the lock file and committing the pending records are then the operator's decision. ProbOS does not remove it."

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-10, A1-1 (in place of P2-11), P2-12, A1-2 to A1-5, N2-1, P2-13 (test markers), R1 (regenerated documents) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

- **M0.** On the base, record the collected count (`--collect-only -q`) of every existing file named in G2. The Architect could not collect them under the bridge (no pytest is allowed). Static counts of `def test_` are 31 in `test_records_store.py`, 13 in `test_ad801_doctor.py`, 22 in `test_ad1270e2f_knowledge_models.py` (parametrised over 23 models), 97 in `test_ad1270e1_config_facade.py`, 7 in `test_config_reference_current.py`, 6 in `test_bf892_spawn_env_guard.py`, 10 in `test_ad1346_admission_effect_census.py`, 3 in `test_layer_boundaries.py`, and 6 in `test_bf084_truncation_and_manuals.py`. The collected counts are what count.
- **G1.** `PY -m pytest tests/test_bf957_records_git_signal.py -q -n 0`.
  - Expected: **5 passed** (T8 ×2, T9 ×3, the guards) and **24 xfailed**.
  - The marker has `raises=AssertionError, strict=True`, so any other exception, or an XPASS, is a FAIL. Any other count is a hard stop.
- **G2.**
  1. `PY -m pytest tests/test_bf957_records_git_signal.py tests/test_records_store.py tests/test_bf084_truncation_and_manuals.py tests/test_bf952_records_keyword_search.py tests/test_ad801_doctor.py tests/test_ad484_ux_adoption.py tests/test_ad1327_verifier_independence.py tests/test_ad1328_s2a_startup_and_doctor.py tests/test_bf901_s3_token_accounting_view.py tests/test_bf906_doctor_check.py tests/test_bf917_template_skills_and_recommission.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1270e1_config_facade.py tests/test_config_reference_current.py tests/test_bf892_spawn_env_guard.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_subprocess_plumbing.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_egress_census.py tests/test_layer_boundaries.py -q -n 0`
  2. `PY -P scripts/check_architecture_principles.py --check`
  3. `PY scripts/check_config_facade.py --check`
  4. `PY scripts/check_config_readers.py` (report-only; none of the three new fields may be listed as unread).
  - Expected: **29 passed** in the new file; every other file 0 failed, with collected counts equal to M0. `test_ad1270e2f` gains no case; its RecordsConfig cases now assert the new values, and it pins a bound sum of 24 over four models; the effect census pins OutsideRuntime 6 and 40 launches. With A1, the 20 files of G2 give 819 passed, 0 failed (derived by the Architect from the oracle's 817 passed and 2 failed before A1; the collected counts do not change). With A3, the new file has 36 passed, and G2 gives 826 passed, 0 failed over the same 20 files (819 + 7 new cases; no other file changes).
- **R1 (inside M2, before G2).**
  - Run `PY scripts/check_config_facade.py --update-baseline`. The diff may touch only the `RecordsConfig` block (three field rows and its `schema_sha256`), and the `schema_sha256` of any model that embeds it (`SystemConfig`). Anything else is a hard stop.
  - Run `PY scripts/gen_config_reference.py`. The diff may add only the three `records` rows.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; `PY -P scripts/gen_ad_ledger.py --check`; `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** Tests use real git in `tmp_path`, as `test_records_store.py` does. Not allowed: a source change made to pass a test, a skip, or a loosened assertion. Any of those goes back to the Architect.
- The broad gate runs once, in the main session with `--receipt`, after the review repairs.

## 5. Commit messages

- M1: `BF-957 M1: tests for the records git signal and the records_git doctor check, xfail until built`
- M2: `BF-957 M2: Ship's Records logs git failures at WARNING once per error, runs one git command at a time, and probos doctor reports a stale lock and a stopped history`
- M3: `BF-957 M3: trackers and ledger`

## 6. Tests (`tests/test_bf957_records_git_signal.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_a_stale_lock_is_logged_once_and_reported_by_doctor_without_a_write` | 1 | **seam**: lock → store write → WARNING once → doctor FAIL, nothing written | M2 |
| T2 | `test_a_failed_git_command_is_logged_once_per_distinct_error_and_returns_its_stdout` | 1 | D3 key, return value | M2 |
| T3 | `test_a_successful_add_or_commit_forgets_the_logged_errors_and_a_read_does_not` | 2 | reset rule | M2 |
| T4 | `test_the_remembered_errors_are_bounded_and_the_oldest_is_dropped` | 1 | bound | M2 |
| T5 | `test_a_timed_out_git_command_is_logged_once_and_still_raises` | 1 | timeout WARNING, raise unchanged | M2 |
| T6 | `test_a_commit_that_raises_is_logged_once_at_warning_and_does_not_raise` | 1 | `_commit`; A4: the warning makes no claim that git did not run | M2; message A4 |
| T7 | `test_one_git_child_runs_at_a_time_per_store` | 1 | D2 lock | M2 |
| T8 | `test_a_commit_with_nothing_staged_is_not_an_error` | 2 | exemption (guard; passes on the base) | none |
| T9 | `test_the_return_value_and_raising_are_unchanged` | 3 | invisible to the 14 call sites (guard; ASCII output; A4's decoding change is T13) | none |
| DC1 | `test_the_doctor_check_is_registered_once_after_disk` | 1 | registration | M2 |
| DC2 | `test_a_lock_is_reported_only_from_its_threshold` | 2 | lock boundary | M2 |
| DC3 | `test_uncommitted_paths_warn_only_over_the_bound` | 2 | count boundary | M2 |
| DC4 | `test_an_old_last_commit_warns_only_with_uncommitted_paths` | 2 | age rule | M2 |
| DC5 | `test_the_check_skips_without_config_records_or_auto_commit` | 3 | skip cases | M2 |
| DC6 | `test_a_missing_directory_or_repository_or_commit_is_reported` | 5 | absent cases; A3 adds "a file" (FAIL); A4 adds "a broken link" (FAIL); A5: the link is always a junction on Windows, a symlink elsewhere | M2; "a file" A3; "a broken link" A4 |
| DC7 | `test_without_git_the_lock_is_still_reported` | 1 | git missing | M2 |
| DC8 | `test_the_check_reads_git_with_optional_locks_off` | 1 | read-only property | M2 |
| CF1 | `test_the_thresholds_are_bounded_config_fields_with_defaults` | 1 | config | M2 |
| T10 | `test_a_commit_that_times_out_is_logged_once_and_not_called_unrun` | 1 | A3 finding 5 | A3 |
| T11 | `test_a_failure_is_logged_with_git_s_first_line_only` | 1 | A3 finding 6, real git, premise on git's advice | A3 |
| T12 | `test_the_warning_memory_changes_under_the_git_lock_and_is_logged_after_its_release` | 3 | A3 finding 4; A4 round-2 F4: the memory changes under `_git_lock`, the record is emitted after its release | A3 (success, failure); A4 (failure, timeout) |
| DC9 | `test_the_check_runs_no_fsmonitor_and_writes_nothing_in_the_repository` | 1 | A3 finding 2, real git, recursive snapshot; A4: `_hermetic_git` isolates git before initialisation, and the initial commit is asserted | A3 |
| T13 | `test_history_is_read_as_utf8_whatever_the_host_locale` | 1 | A4 round-2 F1: a call that leaves decoding to the locale is decoded as cp1252, on any host | A4 |
| T14 | `test_history_is_read_as_stored_whatever_the_configured_encoding` | 4 | A5 round-3 R3-1: `i18n.logOutputEncoding`, `i18n.commitEncoding`, both, and `i18n.commitEncoding` set after the first entry, each CP1252. A7: the premise is that the store's commits carry no encoding label | A5 ("logOutputEncoding", "commitEncoding after the first"); A7 ("commitEncoding", "both", "commitEncoding after the first", at the premise) |
| TI | `test_the_git_isolation_removes_every_git_variable_and_an_external_config_is_unchanged` | 1 | A5 round-3 R3-2: `_isolate_git` (test helper) | A5 (test file) |
| T15 | `test_a_commit_not_written_by_the_store_is_read_in_its_labelled_encoding` | 5 | A6: ISO-8859-1 and Shift_JIS stored in their labelled encoding; a label that begins with `\|`. A7 round-4 F1, F2, F4: a label that holds a carriage return; ISO-8859-1 bytes that are also UTF-8; one launch per read; `limit=1` | A6 (the first three); A7 (all five) |
| T16 | `test_the_store_s_own_message_is_read_as_written_whatever_the_setting` | 4 | A7 round-4 F3: a store message that holds U+FFFD, `\|` and text CP1252 cannot hold, under no setting, `i18n.logOutputEncoding`, `i18n.commitEncoding` and both, each CP1252 | A7 ("commitEncoding", "both") |

All tests run under the autouse fixture `_hermetic_git` (A4, round-2 F3; A5, round-3 R3-2), which calls `_isolate_git` before any store starts: it removes every `GIT_*` variable, then sets `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=<an empty file>` and `GIT_CONFIG_COUNT=0` and points `HOME` and `XDG_CONFIG_HOME` at a temporary directory. So no host `GIT_*` variable (a repository redirect, a configuration file, a command-line scope, a template directory, a commit identity) reaches their git, and git reads no system scope and no global or per-user file but the empty one. Variables outside that class (the locale, `EMAIL`, `PATH`) are not changed; T11 sets `LC_ALL=C` itself, and the store sets its own identity before its first commit.

On the base, each xfail case fails at an `AssertionError`:
- The DC cases fail first at `_check()`'s `assert check is not None`.
- CF1 fails at its `model_fields` assertion.
- T1 to T7 fail at their WARNING-count or `peak` assertions.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf957_records_git_signal.py`:

```python
"""BF-957 (#1760): Ship's Records says when git fails, and probos doctor reports the records repository's state."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.config import RecordsConfig, SystemConfig
from probos.doctor import iter_checks
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.knowledge.records_store import RecordsStore

_LOGGER = "probos.knowledge.records_store"
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-957 M2 builds it")
_THRESHOLDS = {"git_lock_stale_minutes": 10.0, "git_uncommitted_warn_paths": 50, "git_last_commit_warn_hours": 24.0}


def _records(tmp_path: Path, **overrides: object) -> RecordsConfig:
    return RecordsConfig(repo_path=str(tmp_path / "ship-records"), **overrides)


async def _store(tmp_path: Path) -> RecordsStore:
    store = RecordsStore(_records(tmp_path))
    await store.initialize()
    return store


def _git(repo: Path, *args: str, **env: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env={**os.environ, **env},
    ).stdout


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]


def _add_lock_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [m for m in _warnings(caplog) if "git add failed" in m and "index.lock" in m]


def _plant_lock(repo: Path, age_minutes: float = 120.0) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"")
    stamp = time.time() - age_minutes * 60.0
    os.utime(lock, (stamp, stamp))
    return lock


def _check():
    check = next((c for c in iter_checks() if c.name == "records_git"), None)
    assert check is not None, "BF-957: the records_git doctor check is not registered"
    return check


def _ctx(tmp_path: Path, records: RecordsConfig | None, *, loaded: bool = True) -> DoctorContext:
    config = SystemConfig().model_copy(update={"records": records}) if loaded else None
    return DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)


def _fake_run(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    monkeypatch.setattr("probos.knowledge.records_store.subprocess.run", fake)


# ---------------------------------------------------------------- the seam


@_BUILT
@pytest.mark.asyncio
async def test_a_stale_lock_is_logged_once_and_reported_by_doctor_without_a_write(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    repo = store.repo_path
    lock = _plant_lock(repo)
    head = _git(repo, "rev-parse", "HEAD")

    await store.write_entry("bones", "reports/one.md", "First.", "first")
    await store.write_entry("bones", "reports/two.md", "Second.", "second")

    assert (repo / "reports" / "one.md").is_file() and (repo / "reports" / "two.md").is_file()
    assert len(_add_lock_warnings(caplog)) == 1, _warnings(caplog)
    assert _git(repo, "rev-parse", "HEAD") == head

    def snapshot() -> dict[str, tuple[int, int]]:
        return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (repo / ".git").iterdir() if p.is_file()}

    before = snapshot()
    result = await _check().run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.FAIL
    assert "index.lock: present" in result.detail
    pending = re.search(r"uncommitted: (\d+) path", result.detail)
    assert pending is not None and int(pending.group(1)) >= 2
    assert "does not remove" in result.remediation
    assert lock.is_file()
    assert snapshot() == before


# ---------------------------------------------------------------- the signal


@_BUILT
@pytest.mark.asyncio
async def test_a_failed_git_command_is_logged_once_per_distinct_error_and_returns_its_stdout(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)

    first = store._git_sync(("add", "missing-one.md"))
    again = store._git_sync(("add", "missing-one.md"))
    other = store._git_sync(("add", "missing-two.md"))

    assert (first, again, other) == ("", "", "")
    logged = _warnings(caplog)
    assert len(logged) == 2, logged
    assert "missing-one.md" in logged[0] and "missing-two.md" in logged[1]


@_BUILT
@pytest.mark.asyncio
@pytest.mark.parametrize("between", ["a read succeeds", "an add succeeds"])
async def test_a_successful_add_or_commit_forgets_the_logged_errors_and_a_read_does_not(tmp_path, caplog, between):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    lock = _plant_lock(store.repo_path)
    await store.write_entry("bones", "reports/one.md", "First.", "first")
    assert len(_add_lock_warnings(caplog)) == 1

    if between == "a read succeeds":
        assert store._git_sync(("rev-list", "--count", "HEAD")).strip().isdigit()
        expected = 1
    else:
        lock.unlink()
        await store.write_entry("bones", "reports/two.md", "Second.", "second")
        _plant_lock(store.repo_path)
        expected = 2
    await store.write_entry("bones", "reports/three.md", "Third.", "third")

    assert len(_add_lock_warnings(caplog)) == expected


@_BUILT
def test_the_remembered_errors_are_bounded_and_the_oldest_is_dropped(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))
    error = {"text": ""}
    _fake_run(monkeypatch, lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr=error["text"]))

    def fail(i: int) -> None:
        error["text"] = f"fatal: error {i}\n"
        store._git_sync(("status",))

    for i in range(33):
        fail(i)
    assert len(_warnings(caplog)) == 33
    fail(0)  # dropped as the oldest when the 33rd arrived
    assert len(_warnings(caplog)) == 34
    fail(32)  # still remembered
    assert len(_warnings(caplog)) == 34


@_BUILT
def test_a_timed_out_git_command_is_logged_once_and_still_raises(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    _fake_run(monkeypatch, timed_out)
    for _ in range(2):
        with pytest.raises(subprocess.TimeoutExpired):
            store._git_sync(("add", "reports/one.md"))

    logged = _warnings(caplog)
    assert len(logged) == 1, logged
    assert "did not finish" in logged[0] and "lock" in logged[0]


@_BUILT
@pytest.mark.asyncio
async def test_a_commit_that_raises_is_logged_once_at_warning_and_does_not_raise(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))

    async def broken_git(*args: str) -> str:
        raise FileNotFoundError("git")

    monkeypatch.setattr(store, "_git", broken_git)
    await store._commit("first")
    await store._commit("second")

    logged = _warnings(caplog)
    assert len(logged) == 1, logged
    assert "FileNotFoundError" in logged[0]


@_BUILT
def test_one_git_child_runs_at_a_time_per_store(tmp_path, monkeypatch):
    store = RecordsStore(_records(tmp_path))
    counts = {"inside": 0, "peak": 0}
    guard = threading.Lock()
    start = threading.Barrier(2)

    def slow(argv, **kwargs):
        with guard:
            counts["inside"] += 1
            counts["peak"] = max(counts["peak"], counts["inside"])
        time.sleep(0.3)
        with guard:
            counts["inside"] -= 1
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    _fake_run(monkeypatch, slow)

    def call() -> None:
        start.wait()
        store._git_sync(("add", "x.md"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert counts["peak"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("untracked", [False, True], ids=["nothing to commit", "nothing added to commit"])
async def test_a_commit_with_nothing_staged_is_not_an_error(tmp_path, caplog, untracked):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    if untracked:
        (store.repo_path / "reports" / "loose.md").write_text("loose", encoding="utf-8")

    out = store._git_sync(("commit", "-m", "nothing"))

    assert ("nothing added to commit" if untracked else "nothing to commit") in out
    assert _warnings(caplog) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["success", "failure", "git missing"])
async def test_the_return_value_and_raising_are_unchanged(tmp_path, monkeypatch, case):
    store = await _store(tmp_path)
    if case == "success":
        assert store._git_sync(("rev-list", "--count", "HEAD")).strip() == "1"
    elif case == "failure":
        assert store._git_sync(("rev-parse", "--verify", "no-such-ref")) == ""
    else:
        def missing(argv, **kwargs):
            raise FileNotFoundError(argv[0])

        _fake_run(monkeypatch, missing)
        with pytest.raises(FileNotFoundError):
            store._git_sync(("status",))


# ---------------------------------------------------------------- the doctor check


@_BUILT
def test_the_doctor_check_is_registered_once_after_disk():
    names = [c.name for c in iter_checks()]
    assert names.count("records_git") == 1
    assert names[names.index("disk") + 1] == "records_git"


@_BUILT
@pytest.mark.asyncio
@pytest.mark.parametrize(("age", "outcome"), [(9.0, CheckOutcome.OK), (11.0, CheckOutcome.FAIL)])
async def test_a_lock_is_reported_only_from_its_threshold(tmp_path, age, outcome):
    store = await _store(tmp_path)
    _plant_lock(store.repo_path, age_minutes=age)

    result = await _check().run(_ctx(tmp_path, _records(tmp_path, git_lock_stale_minutes=10.0)))

    assert result.outcome == outcome
    assert "index.lock: present" in result.detail


@_BUILT
@pytest.mark.asyncio
@pytest.mark.parametrize(("bound", "outcome"), [(3, CheckOutcome.OK), (2, CheckOutcome.WARN)])
async def test_uncommitted_paths_warn_only_over_the_bound(tmp_path, bound, outcome):
    store = await _store(tmp_path)
    for i in range(3):
        (store.repo_path / "reports" / f"loose-{i}.md").write_text("x", encoding="utf-8")

    result = await _check().run(_ctx(tmp_path, _records(tmp_path, git_uncommitted_warn_paths=bound)))

    assert result.outcome == outcome
    assert "uncommitted: 3 path(s)" in result.detail


@_BUILT
@pytest.mark.asyncio
@pytest.mark.parametrize(("loose", "outcome"), [(False, CheckOutcome.OK), (True, CheckOutcome.WARN)])
async def test_an_old_last_commit_warns_only_with_uncommitted_paths(tmp_path, loose, outcome):
    store = await _store(tmp_path)
    old = "2001-01-01T00:00:00+00:00"
    _git(store.repo_path, "commit", "--allow-empty", "-m", "old", GIT_COMMITTER_DATE=old, GIT_AUTHOR_DATE=old)
    if loose:
        (store.repo_path / "reports" / "loose.md").write_text("x", encoding="utf-8")

    result = await _check().run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == outcome
    assert "last commit:" in result.detail


@_BUILT
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["config not loaded", "records disabled", "auto_commit off"])
async def test_the_check_skips_without_config_records_or_auto_commit(tmp_path, case):
    store = await _store(tmp_path)
    _plant_lock(store.repo_path)
    check = _check()

    if case == "config not loaded":
        result, expected = await check.run(_ctx(tmp_path, None, loaded=False)), CheckOutcome.WARN
    elif case == "records disabled":
        result, expected = await check.run(_ctx(tmp_path, _records(tmp_path, enabled=False))), CheckOutcome.OK
    else:
        result, expected = await check.run(_ctx(tmp_path, _records(tmp_path, auto_commit=False))), CheckOutcome.OK

    assert result.outcome == expected
    assert "index.lock" not in result.detail


@_BUILT
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no directory", "not a repository", "no commit yet"])
async def test_a_missing_directory_or_repository_or_commit_is_reported(tmp_path, case):
    repo = tmp_path / "ship-records"
    if case != "no directory":
        repo.mkdir()
    if case == "no commit yet":
        _git(repo, "init")

    result = await _check().run(_ctx(tmp_path, _records(tmp_path)))

    expected = {"no directory": CheckOutcome.OK, "not a repository": CheckOutcome.WARN, "no commit yet": CheckOutcome.WARN}
    assert result.outcome == expected[case]
    if case == "no commit yet":
        assert "last commit: not read" in result.detail


@_BUILT
@pytest.mark.asyncio
async def test_without_git_the_lock_is_still_reported(tmp_path, monkeypatch):
    store = await _store(tmp_path)
    _plant_lock(store.repo_path)
    check = _check()
    monkeypatch.setattr("probos.doctor.checks.records_git_check.shutil.which", lambda name: None)

    result = await check.run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.FAIL
    assert "git: not found" in result.detail


@_BUILT
@pytest.mark.asyncio
async def test_the_check_reads_git_with_optional_locks_off(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")  # an ambient value the check must override, on any host
    await _store(tmp_path)
    check = _check()
    seen: list[str | None] = []
    real_run = subprocess.run

    def spy(argv, **kwargs):
        seen.append((kwargs.get("env") or {}).get("GIT_OPTIONAL_LOCKS"))
        return real_run(argv, **kwargs)

    monkeypatch.setattr("probos.doctor.checks.records_git_check.subprocess.run", spy)
    result = await check.run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.OK
    assert seen == ["0", "0"]


@_BUILT
def test_the_thresholds_are_bounded_config_fields_with_defaults():
    fields = RecordsConfig.model_fields
    assert {name: fields[name].default for name in _THRESHOLDS if name in fields} == _THRESHOLDS
    for name in _THRESHOLDS:
        assert fields[name].description
        with pytest.raises(ValidationError):
            RecordsConfig(**{name: 0})
```

### 7.2 M2

**P2-1.** `src/probos/knowledge/records_store.py`
SEARCH:
```
import re
import subprocess
from collections import Counter
```
REPLACE:
```
import re
import subprocess
import threading
from collections import Counter
```

**P2-2.** `records_store.py`
SEARCH:
```
logger = logging.getLogger(__name__)

# Directory structure per AD-434 design
```
REPLACE:
```
logger = logging.getLogger(__name__)

# BF-957: how many distinct git errors one store remembers so that each is logged once; past this the oldest is dropped.
_GIT_WARNED_MAX = 32
# BF-957: the git verbs that take the index lock. A zero exit of one forgets every remembered error.
_GIT_INDEX_VERBS = frozenset({"add", "commit"})
# BF-957: a commit with nothing staged exits non-zero and says so on stdout; it is not an error.
_GIT_NOTHING_STAGED = ("nothing to commit", "nothing added to commit")


def _git_error_line(stderr: str, stdout: str) -> str:
    """BF-957: the first non-empty line a failed git command printed. Two failures with the same line are one error."""
    for text in (stderr, stdout):
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:300]
    return "(no output)"


# Directory structure per AD-434 design
```

**P2-3.** `records_store.py`
SEARCH:
```
        self._commit_lock = asyncio.Lock()
        self._pending_commits: list[str] = []
```
REPLACE:
```
        self._commit_lock = asyncio.Lock()
        # BF-957: one git child of this store at a time, held from launch until the child has exited.
        self._git_lock = threading.Lock()
        # BF-957: the git errors already logged, oldest first; read and written only under _git_warned_lock.
        self._git_warned: dict[tuple[str, str], None] = {}
        self._git_warned_lock = threading.Lock()
        self._pending_commits: list[str] = []
```

**P2-4 and P2-5.** `records_store.py`
SEARCH:
```
    def _git_sync(self, args: tuple[str, ...]) -> str:
        """Synchronous git execution."""
        result = subprocess.run(
            ["git"] + list(args),
            env=trusted_command_env(),
            cwd=str(self._repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            if result.stderr.strip():
                logger.debug("git %s stderr: %s", args[0], result.stderr.strip())
        return result.stdout

    async def _commit(self, message: str) -> None:
        """Debounced git commit."""
        if not self._config.auto_commit:
            return
        async with self._commit_lock:
            try:
                await self._git("commit", "-m", message, "--allow-empty-message")
            except Exception as e:
                logger.debug("Git commit skipped: %s", e)
```
REPLACE:
```
    def _git_sync(self, args: tuple[str, ...]) -> str:
        """Synchronous git execution.

        BF-957: at most one git child of this store runs at a time (``_git_lock``, held until the child has
        exited), so the store's own commands never meet at the index lock. A non-zero exit is logged at WARNING
        once per distinct error (``_warn_git_once``) and its stdout is returned as before; a commit with nothing
        staged is not an error. A command that outlives the timeout is stopped by ``subprocess.run``; this logs
        a WARNING, because a lock it held may remain, and re-raises the same exception.
        """
        verb = args[0] if args else ""
        with self._git_lock:
            try:
                result = subprocess.run(
                    ["git"] + list(args),
                    env=trusted_command_env(),
                    cwd=str(self._repo_path),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                self._warn_git_once(
                    (verb, "timeout"),
                    "Ship's Records: git %s did not finish in 30 s and was stopped; a lock file it held may "
                    "remain in %s. `probos doctor` reports the repository's state.",
                    verb,
                    self._repo_path / ".git",
                )
                raise
        if result.returncode == 0:
            if verb in _GIT_INDEX_VERBS:
                self._forget_git_warnings()
            return result.stdout
        if any(phrase in result.stdout for phrase in _GIT_NOTHING_STAGED):
            return result.stdout
        self._warn_git_once(
            (verb, _git_error_line(result.stderr, result.stdout)),
            "Ship's Records: git %s failed (exit %d): %s. Records are still written to disk, but a failed add "
            "or commit leaves them out of the records history. This error is logged once until a git add or "
            "commit succeeds; `probos doctor` reports the repository's state.",
            verb,
            result.returncode,
            (result.stderr.strip() or result.stdout.strip() or "(no output)")[:2000],
        )
        return result.stdout

    def _warn_git_once(self, key: tuple[str, str], msg: str, *args: object) -> None:
        """BF-957: log ``msg`` at WARNING unless ``key`` was logged since the last successful git add or commit.

        At most ``_GIT_WARNED_MAX`` keys are remembered; past that the oldest is dropped and may be logged again.
        """
        with self._git_warned_lock:
            if key in self._git_warned:
                return
            if len(self._git_warned) >= _GIT_WARNED_MAX:
                self._git_warned.pop(next(iter(self._git_warned)))
            self._git_warned[key] = None
        logger.warning(msg, *args)

    def _forget_git_warnings(self) -> None:
        """BF-957: a git add or commit succeeded, so any earlier error that recurs is logged again."""
        with self._git_warned_lock:
            self._git_warned.clear()

    async def _commit(self, message: str) -> None:
        """Debounced git commit.

        BF-957: an exception (a timeout, git missing) is logged at WARNING once per exception type until a git
        add or commit succeeds, and is not raised, as before.
        """
        if not self._config.auto_commit:
            return
        async with self._commit_lock:
            try:
                await self._git("commit", "-m", message, "--allow-empty-message")
            except Exception as e:
                self._warn_git_once(
                    ("commit", type(e).__name__),
                    "Ship's Records: git commit did not run (%s: %s). The record is written to disk but not to "
                    "the records history. Logged once until a git add or commit succeeds.",
                    type(e).__name__,
                    e,
                )
```

**P2-6.** `src/probos/config_models/knowledge.py`
SEARCH:
```
    # Tier 2 from it. Default-OFF — when False, Tier 2 uses the keyword path.
    semantic_index_enabled: bool = False


class ArchiveConfig(BaseModel):
```
REPLACE:
```
    # Tier 2 from it. Default-OFF — when False, Tier 2 uses the keyword path.
    semantic_index_enabled: bool = False
    # BF-957: probos doctor's records_git check reads these; the store's behaviour does not depend on them.
    git_lock_stale_minutes: float = Field(
        default=10.0,
        gt=0,
        description=(
            "BF-957: probos doctor reports the records repository's .git/index.lock as stale (FAIL) once it is "
            "this many minutes old. Ship's Records stops its own git commands after 30 seconds."
        ),
    )
    git_uncommitted_warn_paths: int = Field(
        default=50,
        ge=1,
        description=(
            "BF-957: probos doctor warns when the records repository holds more than this many uncommitted "
            "paths, untracked or modified."
        ),
    )
    git_last_commit_warn_hours: float = Field(
        default=24.0,
        gt=0,
        description=(
            "BF-957: probos doctor warns when the records repository's last commit is at least this many hours "
            "old while uncommitted paths exist."
        ),
    )


class ArchiveConfig(BaseModel):
```

**N2-1.** New file `src/probos/doctor/checks/records_git_check.py`:

```python
"""BF-957: is Ship's Records' git history still growing?

Three readings of the records repository: an ``index.lock`` at least ``records.git_lock_stale_minutes`` old
(FAIL: every git add and commit fails while it remains), more uncommitted paths than
``records.git_uncommitted_warn_paths`` (WARN), and a last commit at least ``records.git_last_commit_warn_hours``
old while uncommitted paths exist (WARN).

The check writes nothing and takes no lock. The lock is read with ``stat``, and both git commands run with
``GIT_OPTIONAL_LOCKS=0``, so ``git status`` does not refresh the index. It removes nothing either: removing a
lock stays the operator's decision once no git process uses the repository.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from probos.config import resolve_records_repo_path
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.execution.command_env import trusted_command_env

#: Seconds each read-only git command may take. Stopping one holds no lock: optional locks are off.
_GIT_READ_TIMEOUT_S = 15.0
_RANK = {CheckOutcome.OK: 0, CheckOutcome.WARN: 1, CheckOutcome.FAIL: 2}
_HEADLINE = {
    CheckOutcome.OK: "Ship's Records git: history is being kept",
    CheckOutcome.WARN: "Ship's Records git: needs attention",
    CheckOutcome.FAIL: "Ship's Records git: history has stopped",
}

_Part = tuple[CheckOutcome, str, str]  # (outcome, detail line, remediation)


def _git_read_sync(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One read-only git command in ``repo``, with optional locks off so nothing in the repository is written."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**trusted_command_env(), "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_READ_TIMEOUT_S,
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return "(no output)"


def _lock_part(repo: Path, git_dir: Path, records: Any) -> _Part:
    lock = git_dir / "index.lock"
    try:
        modified = lock.stat().st_mtime
    except FileNotFoundError:
        return CheckOutcome.OK, "index.lock: none", ""
    except OSError as exc:
        return CheckOutcome.WARN, f"index.lock: could not be read ({type(exc).__name__})", ""
    age_min = max(0.0, (time.time() - modified) / 60.0)
    if age_min >= records.git_lock_stale_minutes:
        return (
            CheckOutcome.FAIL,
            f"index.lock: present for {age_min:.0f} min (threshold {records.git_lock_stale_minutes:g} min); "
            "every git add and commit of Ship's Records fails while it remains",
            f"A git process that ended without cleaning up leaves {lock}. With the vessel stopped and no git "
            f"process using {repo}, back up {git_dir}; removing the lock file and committing the pending records "
            "are then the operator's decision. ProbOS does not remove it.",
        )
    return (
        CheckOutcome.OK,
        f"index.lock: present for {age_min:.0f} min, under the {records.git_lock_stale_minutes:g} min threshold "
        "(a git command may be running)",
        "",
    )


def _git_parts(repo: Path, records: Any) -> list[_Part]:
    if shutil.which("git") is None:
        return [(CheckOutcome.WARN, "git: not found on PATH; uncommitted paths and the last commit were not read", "")]
    try:
        status = _git_read_sync(repo, "status", "--porcelain", "--untracked-files=all", "--no-renames", "-z")
        last = _git_read_sync(repo, "log", "-1", "--format=%ct")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [(CheckOutcome.WARN, f"git: could not read the repository ({type(exc).__name__})", "")]
    if status.returncode != 0:
        return [(CheckOutcome.WARN, f"git status failed (exit {status.returncode}): {_first_line(status.stderr)}", "")]
    parts: list[_Part] = []
    pending = sum(1 for entry in status.stdout.split("\0") if entry)
    if pending > records.git_uncommitted_warn_paths:
        parts.append((
            CheckOutcome.WARN,
            f"uncommitted: {pending} path(s), over the bound of {records.git_uncommitted_warn_paths}",
            "Uncommitted records are not in the records history. The vessel's log names each git failure "
            "('Ship's Records: git ...').",
        ))
    else:
        parts.append((CheckOutcome.OK, f"uncommitted: {pending} path(s)", ""))
    try:
        committed = int(last.stdout.strip()) if last.returncode == 0 else None
    except ValueError:
        committed = None
    if committed is None:
        parts.append((CheckOutcome.WARN, f"last commit: not read (exit {last.returncode}: {_first_line(last.stderr)})", ""))
        return parts
    age_h = max(0.0, (time.time() - committed) / 3600.0)
    if pending and age_h >= records.git_last_commit_warn_hours:
        parts.append((
            CheckOutcome.WARN,
            f"last commit: {age_h:.1f} h ago with {pending} uncommitted path(s) "
            f"(threshold {records.git_last_commit_warn_hours:g} h)",
            "",
        ))
    else:
        parts.append((CheckOutcome.OK, f"last commit: {age_h:.1f} h ago", ""))
    return parts


def _inspect(repo: Path, git_dir: Path, records: Any) -> CheckResult:
    parts = [_lock_part(repo, git_dir, records), *_git_parts(repo, records)]
    worst = max((outcome for outcome, _, _ in parts), key=_RANK.__getitem__)
    return CheckResult(
        outcome=worst,
        message=f"{_HEADLINE[worst]} ({repo})",
        remediation=" ".join(text for _, _, text in parts if text),
        detail="\n".join(line for _, line, _ in parts),
    )


@dataclass(frozen=True)
class _RecordsGitCheck:
    name: str = "records_git"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        records = getattr(ctx.config, "records", None) if ctx.config is not None else None
        if records is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Ship's Records git: not checked, because the configuration did not load",
            )
        if not records.enabled:
            return CheckResult(outcome=CheckOutcome.OK, message="Ship's Records git: records are disabled in config")
        if not records.auto_commit:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Ship's Records git: auto_commit is off, so ProbOS keeps no records history to check",
            )
        repo = resolve_records_repo_path(records, ctx.data_dir)
        if not repo.is_dir():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message=f"Ship's Records git: {repo} does not exist yet; it is created when the vessel starts",
            )
        git_dir = repo / ".git"
        if not git_dir.is_dir():
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Ship's Records git: {repo} is not a git repository, so records have no history",
                remediation="Ship's Records initialises the repository when the vessel starts.",
            )
        return await asyncio.to_thread(_inspect, repo, git_dir, records)


register_check(_RecordsGitCheck())
```

**P2-7.** `src/probos/doctor/checks/__init__.py`
SEARCH:
```
    disk_check,
    federation_check,
```
REPLACE:
```
    disk_check,
    records_git_check,  # BF-957: after disk, before federation
    federation_check,
```

**P2-8.** `tests/test_bf892_spawn_env_guard.py`
SEARCH:
```
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, "docker info: DOCKER_HOST"),
```
REPLACE:
```
    ("src/probos/doctor/checks/records_git_check.py", "_git_read_sync"): (1, "git status/log on the records repo, GIT_OPTIONAL_LOCKS=0 (BF-957)"),
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, "docker info: DOCKER_HOST"),
```

**P2-9.** `tests/fixtures/ad1346_effect_census.py`
SEARCH:
```
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, OutsideRuntime("docker info for probos doctor")),
```
REPLACE:
```
    ("src/probos/doctor/checks/records_git_check.py", "_git_read_sync"): (1, OutsideRuntime("git status/log for probos doctor's records_git check")),
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, OutsideRuntime("docker info for probos doctor")),
```

**P2-10.** `tests/test_ad1270e2f_knowledge_models.py`
SEARCH:
```
                         'notebook_staleness_alert_rate': 0.7,
                         'semantic_index_enabled': False},
```
REPLACE:
```
                         'notebook_staleness_alert_rate': 0.7,
                         'semantic_index_enabled': False,
                         # BF-957 appended three fields after the move; the move changed none.
                         'git_lock_stale_minutes': 10.0,
                         'git_uncommitted_warn_paths': 50,
                         'git_last_commit_warn_hours': 24.0},
```

**P2-11.** Replaced by A1-1 (§7.2a), which is the same edit as a fenced pair. Do not apply it here.

**P2-12.** `tests/test_ad1270e1_config_facade.py`
SEARCH:
```
    # AD-1356 S4 (#1722) adds ApprovalInboxConfig's three agent_work_*_decider fields (1880 -> 1883).
    assert counts["field_definitions"] == 1883  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # AD-1356 S4 (#1722) adds ApprovalInboxConfig's three agent_work_*_decider fields (1880 -> 1883).
    # BF-957 (#1760) adds RecordsConfig's three git_* doctor thresholds (1883 -> 1886).
    assert counts["field_definitions"] == 1886  # AD-1206 intentionally adds github_repository.
```

**P2-13.** In `tests/test_bf957_records_git_signal.py`, delete the line `_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-957 M2 builds it")` and each of the 16 lines that is exactly `@_BUILT`.

**R1.** Regenerate the two documents as in §4.

### 7.2a Amendment A1 (milestone M2, applied after P2-12 and before P2-13)

Each SEARCH below occurs once in its file at the state P2-1 to P2-12 leave, with P2-11 skipped. The anchor is `baea653d` plus P2-10, which does not touch these lines. Working copies are CRLF; the SEARCH text is LF.

**A1-1.** `tests/test_ad1270e2f_knowledge_models.py`. **This pair replaces P2-11. Do not also apply P2-11.**
SEARCH:
```
    "RecordsConfig": 0,
```
REPLACE:
```
    "RecordsConfig": 3,  # BF-957: the three git_* doctor thresholds (gt, ge, gt)
```

**A1-2.** The same file (the comment above the table)
SEARCH:
```
#: Numeric bounds (Ge/Gt/Le/Lt) declared per model, counted on the PRE-MOVE
#: source. Pinning the exact count per model is what makes the case below
#: non-vacuous: twenty of the twenty-three carry no bound at all, so a bare
```
REPLACE:
```
#: Numeric bounds (Ge/Gt/Le/Lt) declared per model, counted on the PRE-MOVE
#: source, except RecordsConfig's three, which BF-957 (#1760) appended after the
#: move. Pinning the exact count per model is what makes the case below
#: non-vacuous: nineteen of the twenty-three carry no bound at all, so a bare
```

**A1-3.** The same file (docstring of `test_every_declared_bound_is_still_enforced`)
SEARCH:
```
    bound and still pass. The count is pinned per model, from the pre-move
    source, and must match exactly.
```
REPLACE:
```
    bound and still pass. The count is pinned per model, from the pre-move
    source plus BF-957's three RecordsConfig bounds, and must match exactly.
```

**A1-4.** The same file (`test_the_bound_table_is_exhaustive_and_not_all_zero`)
SEARCH:
```
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 21
    assert sorted(n for n, c in EXPECTED_BOUND_COUNTS.items() if c) == [
        "LLMRateConfig",
        "PredictiveBranchingConfig",
        "SelfImprovementConfig",
    ]
```
REPLACE:
```
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 24  # BF-957: RecordsConfig +3
    assert sorted(n for n, c in EXPECTED_BOUND_COUNTS.items() if c) == [
        "LLMRateConfig",
        "PredictiveBranchingConfig",
        "RecordsConfig",
        "SelfImprovementConfig",
    ]
```

**A1-5.** `tests/test_ad1346_admission_effect_census.py`
SEARCH:
```
    assert by_kind == {Sink: 12, System: 19, OutsideRuntime: 5, Pending: 0, Unreached: 3}, by_kind  # AD-1346 M3e2b
    assert sum(type(cover) is Sink for _count, cover in SUBPROCESS_SITES.values()) == 8
    assert [site for site, (_count, cover) in SUBPROCESS_SITES.items() if type(cover) is Pending] == []  # AD-1346 M3e2b: D160's zero
    assert sum(found.values()) == 39
```
REPLACE:
```
    assert by_kind == {Sink: 12, System: 19, OutsideRuntime: 6, Pending: 0, Unreached: 3}, by_kind  # AD-1346 M3e2b; BF-957: records_git +1
    assert sum(type(cover) is Sink for _count, cover in SUBPROCESS_SITES.values()) == 8
    assert [site for site, (_count, cover) in SUBPROCESS_SITES.items() if type(cover) is Pending] == []  # AD-1346 M3e2b: D160's zero
    assert sum(found.values()) == 40  # BF-957: + doctor records_git_check._git_read_sync
```

### 7.2b Amendment A3 (review round 1; milestones A3-M1 and A3-M2, on `2f6087ad`)

The cross-family Diff Reviewer's round-1 report (NOT READY, seven findings) is answered below. The SEARCH/REPLACE pairs are in the Architect's A3 consult answer; the built code is the record.

| Finding | Decision | Where |
|---|---|---|
| 1. A raising log handler aborts a write | Recorded (injected-only) | L12 |
| 2. The doctor's git runs a configured fsmonitor | Fixed: `HARDENED_GIT_CONFIG_ARGS` on both reads | `_git_read_sync`; DC9; D-8 |
| 3. A path that is a file reads as "does not exist yet" | Fixed: FAIL | `run`; DC6 "a file"; D-7 |
| 4. The memory changed after `_git_lock` was released | Fixed: classified under the lock | `_git_sync`; T12; R-12 |
| 5. A timeout called an unrun commit, logged twice | Fixed: "not known"; `_commit` does not log a timeout again | `_git_sync`, `_commit`; T10; R-10 |
| 6. The WARNING carried git's removal advice | Fixed: git's first line only | `_git_sync`; T11; R-11 |
| 7. L8 missed the dream cycle's `git add -A` | Fixed: L8 corrected | §10 |

- **A3-M1 (HIGH).** Tests first: the new file gives 6 failed (T10, T11, T12 "success" and "failure", DC6 "a file", DC9; each at an `AssertionError`) and 30 passed. After the source: 36 passed. Then G2: 826 passed, 0 failed.
- **A3-M2 (docs).** This contract, plus the PROGRESS and DECISIONS entries.
- **Shared contracts.** None: no public signature, persisted format, config field, event type or gate changes. `probos doctor` changes its outcome only for a records path that exists and is not a directory (OK to FAIL). R-4 moves four spaces deeper.

### 7.2c Amendment A4 (review round 2; milestones A4-M1 and A4-M2, on `2fc26a66`)

The cross-family Diff Reviewer's round-2 report (NOT READY, six findings) is answered below. The SEARCH/REPLACE pairs are in the Architect's A4 consult answer; the built code is the record.

| Finding | Decision | Where |
|---|---|---|
| F1. Git output decoded with the locale codec; on cp1252 an undecodable byte made a successful read return `None`, so the history API lost committed rows (pre-existing) | Fixed here: `encoding="utf-8", errors="replace"`, as the doctor's reads have. The return-value claim is widened by this one case | `_git_sync`; T13; R-15 |
| F2. A Windows junction whose target was removed read as "does not exist yet" (OK) while startup refuses it | Fixed: absent only when `lstat` raises `FileNotFoundError`; an entry that is not a directory is FAIL | `run`; DC6 "a broken link"; D-7, D-9 |
| F3. The real-git tests read the host's git configuration and redirects, and decoded with the locale | Fixed: autouse `_hermetic_git` before any store starts; all test git output decoded as UTF-8; DC9 asserts the initial commit | test file |
| F4. `_git_sync` logged while holding `_git_lock`; a handler that reads git through the store deadlocked | Fixed: the memory decision under `_git_lock`, the emission after its release, on the timeout path too | `_git_sync`, `_remember_git_warning`; T12; R-12 to R-14 |
| F5. A3's exceptional-path sentences were false | Fixed: `_commit`'s warning makes no claim about whether git ran; cancellation propagates, as before; the lock claim is narrowed to `_git_sync` | `_commit`; T6; R-16; §13, trackers |
| F6. L12 said Python's handlers report their errors through `handleError` | Fixed: L12 narrowed, with the reviewer's `FileHandler(delay=True)` counterexample; L13 added | §10 |

- **A4-M1 (HIGH).** Tests first: the new file gives 5 failed (T6; T12 "failure" and "timeout"; T13; DC6 "a broken link", which fails only on Windows, where the link is a junction; each at an `AssertionError`) and 33 passed. After the source: 38 passed. Then G2: 828 passed, 0 failed.
- **A4-M2 (docs).** This contract, the PROGRESS and DECISIONS entries, the ledger (G3).
- **Return values (F1).** On a host whose locale codec is UTF-8 nothing changes. Elsewhere (Windows: cp1252), a read returns git's text. Output the codec could not decode (a byte undefined in cp1252, such as `0x81` in `Ё`) came back as `None` with exit 0, which `get_history` turned into `[]` and `get_stats` into 0 commits. Output it could decode was misread: by the cp1252 table, the em dash of every records commit message reads as three characters (derived, not measured). A decode error, which the base raised on a POSIX host with a non-UTF-8 locale, no longer occurs.
- **Shared contracts.** None: no public signature, persisted format, config field, event type or gate changes. The history API keeps its shape. `_git_sync` still holds the store's one launch (census and env-guard rows unchanged). `probos doctor` changes its outcome for a link whose target is missing (OK to FAIL); an `lstat` error other than "not found" now reaches the runner, which reports FAIL.
- **Campaign.** Both source files change, so A3's campaign does not carry over. Rows R-1, R-4, R-6, R-11, R-12, D-7 and D-8 are rewritten; R-13 to R-16 and D-9 are new. Run all 25 rows on A4's head. Also rerun the reviewer's two F3 probes on A4's head: DC9 must pass with a global `commit.gpgSign=true` in the host's real global config, and T11 must pass under a Unicode `--basetemp`.

### 7.2d Amendment A5 (review round 3; milestones A5-M1 and A5-M2, on `5d284e2b`)

The round-3 delta review (NOT READY, four findings, three introduced by A4) is answered below. The round-three brake decision was **continue**, with this scope. §7.2c stays the record of A4; its rows F1, F3 and F4 are qualified here.

| Finding | Decision | Where |
|---|---|---|
| R3-1. A configured `i18n.logOutputEncoding` made `git log` re-encode the message, and A4's UTF-8 decoding garbled it (regression of A4) | Fixed: `get_history` reads every commit with `--encoding=UTF-8` and `%e` (its encoding label), then re-reads the commits of each other label with that label as the output encoding, from the same newest commit; git outputs a subject as stored when the output encoding equals its label. Rejected, by measurement: one `--encoding=utf-8` (an operator's `i18n.commitEncoding` labels the store's UTF-8 messages without converting them, and git converts them again); `--encoding=none` (on Git for Windows it re-encodes to the locale's charset). Residual: L15 | `get_history`; T14; R-17 to R-19 |
| R3-2. `_hermetic_git` removed a list of names and missed `GIT_CONFIG`, so the store's `git config` wrote to the host's file | Fixed by class: `_isolate_git` removes every `GIT_*` variable before it sets its own three; TI tests the helper | test file; TI; H-1 |
| R3-3. DC6 "a broken link" built a symlink wherever one could be created, which A3's check already refused, so only a Windows host without the symlink privilege guarded the junction fix | Fixed: on Windows always a junction, with an `os.path.isjunction` premise; a symlink elsewhere | test file; DC6; D-10 |
| R3-4. "does not wait on it" and "No log record is emitted while `_git_lock` is held" were stronger than the code: another thread's command may hold the lock when a handler reads git | Text qualified; the code does not change. L14 records the wait | `_git_sync` docstring; §13 property 2; L12; L14; T12 comment |

- **A5-M1 (HIGH).** Before building, the orchestrator ran probe P-E (the Architect's A5 answer). Tests first: the new file gives 2 failed (T14 "logOutputEncoding", measured on A4's argv; T14 "commitEncoding after the first", derived from P-E step 8), each at an `AssertionError`, and 41 passed. After the source: 43 passed. Then G2.
- **A5-M2 (docs).** This contract, the PROGRESS and DECISIONS entries, the ledger (G3).
- **Sweep.** The sentences A4 added or rewrote in this contract, `DECISIONS.md`, `PROGRESS.md`, the docstrings, comments and test comments were reread for "no", "never", "does not wait", "cannot", "hermetic", "all", "always" and "only" against the code. Changed: the four findings above, the `encoding=` comment in `_git_sync` ("git writes UTF-8"), the T12 comment ("cannot deadlock"), L13's "git never creates one", and this section's qualification of §7.2c. The fixture keeps its name; §6 states what it isolates.
- **Shared contracts.** None. `get_history` keeps its signature and row shape. It runs one `git log` as before, plus one more for each distinct non-empty encoding label among the listed commits; there is none in a repository without `i18n.commitEncoding` (round-4 F4: false; a history can hold labels while the setting is unset. A7 removes the second read: §7.2f). Every launch goes through `_git_sync`, whose argv, environment and launch count are unchanged (census and env-guard rows unchanged).
- **Campaign.** `records_store.py` and the test file change; `records_git_check.py` does not. Run all 30 rows on A5's head: the 25 from A4 (R-15 and D-7 rewritten), plus R-17, R-18, R-19, D-10 and H-1. D-10 is killed on Windows only: POSIX has no junction, and A3's shape refuses a broken symlink there. No row covers pass 2's start at `entries[0]["commit"]`: it only matters when a commit lands between the two reads, and no test makes one land there (L15). Rerun the round-3 probes on A5's head: the configured-encoding probe returns `[records] café — by bones`, and DC9 with `GIT_CONFIG=<a scratch file>` passes and leaves the file unchanged.

### 7.2e Amendment A6 (before review round 4; milestones A6-M1 and A6-M2, on `9612556c`)

Before round 4, the orchestrator measured `get_history` with the real store and real git over five commit kinds and four read-time settings (no setting; `i18n.logOutputEncoding` CP1252 or Shift_JIS; `i18n.commitEncoding` CP1252). A5 read a commit not written by the store, stored in its labelled encoding (ISO-8859-1, Shift_JIS), with replacement characters under every setting; A4 had read five of those eight cells right. A5's second read replaced git's correct conversion with stored bytes that are not UTF-8. Wrong cells: A4 9, A5 8, A6 0. §7.2d's R3-1 row is qualified here.

| Change | Where |
|---|---|
| The second read's text replaces the first only when it holds no U+FFFD after `_git_sync`'s decoding, that is, when the stored bytes are UTF-8; otherwise git's conversion from the label stands. Measured over the whole matrix before building | `get_history`; T15 "ISO-8859-1", "Shift_JIS"; R-20 |
| Fields are separated by NUL, not `\|`: git writes the configured value as the label, so a label that begins with `\|` shifted A5's fields (an empty label, and the message prefixed), where A4, which did not read the label, was right (probe P-F) | `get_history`; T15 "a label that begins with a pipe"; R-21 |

- **A6-M1 (HIGH).** Before building, the orchestrator ran probe P-F (the Architect's A6 answer). Tests first: the new file gives 3 failed (T15 "ISO-8859-1" and "Shift_JIS", measured on A5's head by the matrix; "a label that begins with a pipe", P-F step 2), each at an `AssertionError`, and 43 passed. After the source: 46 passed. Then G2.
- **A6-M2 (docs).** This contract, the PROGRESS and DECISIONS entries, the ledger (G3).
- **Shared contracts.** None. The same launches as A5; the row shape is unchanged. (Round-4 F4: false for a label that begins with `|`: one launch on A5, two on A6. A7 removes the second read: §7.2f.)
- **Campaign.** `records_store.py` and the test file change. Run all 32 rows on A6's head: A5's 30 (R-17 and R-18 rewritten for the NUL separator) plus R-20 and R-21. Rerun the orchestrator's matrix on A6's head: no cell is wrong.
- **Review.** Round 4 reviews A5 and A6 as one delta, `5d284e2b` to A6's head.

### 7.2f Amendment A7 (review round 4; milestones A7-M1 and A7-M2, on `88e2d216`)

Round 4 reviewed A5 and A6 as one delta: NOT READY, four must-fix findings and one scheduled. The round-four brake decision was **continue**, with this scope. Round 5 reviews A7 only. After round 5, a finding that is neither a P1 nor a regression against the base `46950c39` reached by an unconfigured host is recorded, not repaired. §7.2d and §7.2e stay the records of A5 and A6; their history design is replaced here.

A5 and A6 repaired at read time an ambiguity created at write time. An operator's `i18n.commitEncoding` labels the store's UTF-8 messages without converting them, so a labelled commit's bytes may be the store's UTF-8 or text correctly stored in its label, and no reader can tell them apart. A7 removes the ambiguity where it starts. Every `git commit` the store runs pins `i18n.commitEncoding=UTF-8`, so the store's commits are never labelled. `get_history` returns to one `git log` with `--encoding=UTF-8`, which git outputs as stored for an unlabelled commit and for a label it cannot convert from (L15), and converts from its label for any other.

| Finding | Decision | Where |
|---|---|---|
| F1. An exception in a per-label read discarded every first-read row (introduced by A5) | Fixed by construction: one read. Its failures return `[]` as on the base | `get_history`; T15 (one launch) |
| F2. A carriage return in a label split the record (A5) | Fixed by construction: the label is neither read nor passed to git | `get_history`; T15 "a label that holds a carriage return" |
| F3. A6 took a legitimate U+FFFD for a decoding replacement (A6) | Fixed for every commit the store writes: unlabelled, output as stored. A commit an older store labelled is read as git converts it (L15) | `_git_sync` (`pin`); T14 premise; T16; R-22 |
| F4. The launch sentences of §7.2d and §7.2e were false | Annotated in place; one launch per read | §7.2d; §7.2e; T15 |
| F5. A carriage return in a subject cuts it (pre-existing: base and every amendment alike) | Recorded, with a follow-up | L16 |

Cells are judged against the base, because no amendment shipped. A7 reads ISO-8859-1 bytes that are also UTF-8 as git converts them (L15's former residual (1), now right). A7 is worse than A6 in one class, a labelled commit an older store wrote under an operator's `i18n.commitEncoding`. A6 read it right (not the empty label: L15 (1)); A7 reads it as git converts it. With a cp1252 decoder the base reads it the same or worse (probe P-G5). With a UTF-8 decoder (a POSIX UTF-8 locale, or `PYTHONUTF8=1`) the base read a commit labelled CP1252, or with an empty label, right when a read-time `i18n.logOutputEncoding` or `i18n.commitEncoding` was CP1252, and wrong with no setting, so A7 regresses against the base there (probes P-G5 and P-G7 under both decoders; round-5 finding 1, recorded under the brake: L15 (1)). The class exists only on a host that set `i18n.commitEncoding` before this change.

- **A7-M1 (HIGH).** Before building, the orchestrator ran probes P-G1 to P-G7 and its matrix and mixed-history scripts with a base column (the Architect's A7 answer). Tests first: the new file gives 10 failed, each at an `AssertionError`, and 42 passed. The failures: T14 "commitEncoding", "both" and "commitEncoding after the first" at the label premise; T15 "ISO-8859-1", "Shift_JIS" and "a label that begins with a pipe" at the launch count, and "a label that holds a carriage return" and "ISO-8859-1 bytes that are also UTF-8" at the history; T16 "commitEncoding" and "both". After the source: 52 passed. Then G2.
- **A7-M2 (docs).** This contract, the PROGRESS and DECISIONS entries, the ledger (G3).
- **Shared contracts.** `_git_sync` puts `-c i18n.commitEncoding=UTF-8` before `commit` for the two `commit` call sites (census rows 5 and 14) and for no other verb. Its verb, return value, environment and launch count are unchanged, so the census and env-guard rows do not change. With no operator setting, git's default commit encoding is already UTF-8, so the commit objects match the base's (P-G1). `get_history` makes one launch, as on the base; signature and row shape unchanged.
- **Campaign.** `records_store.py` and the test file change; `records_git_check.py` does not. Rows R-18 to R-21 are deleted (their lines are gone), R-17 is rewritten and R-22 is new. Run every row on A7's head. Rerun the matrix and the mixed-history script with a base column: no cell is wrong outside L15 (1) and (2), and no cell is worse than the base with this host's cp1252 decoder (with a UTF-8 decoder see L15 (1)).
- **Review.** Round 5 reviews A7 only, `88e2d216` to A7's head. The brief gives the class table in the Architect's A7 answer as properties, says that regressions are judged against the base, and points to L15 (1) as recorded.

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it. Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-957 (DATE), #1760 -- Ship's Records says when git fails, and `probos doctor` reports a stopped records history.**
- **Base.** `RecordsStore._git_sync` logged a non-zero git exit at DEBUG, and `_commit` logged a commit that raised at DEBUG. A stale `.git/index.lock`, which makes every `git add` and `git commit` fail, therefore stopped the records history with no signal while records were still written.
- **Signal.** Each failed git command is logged at WARNING, once per distinct error until a git add or commit succeeds, with at most 32 errors remembered. A commit with nothing staged is not an error. Return values and raised exceptions are unchanged. A command stopped by the 30-second timeout is logged at WARNING before its exception propagates, because a lock it held may remain.
- **One git command at a time.** On the base only `git commit` was serialized, so a store's own `git add` calls could meet at the index lock and leave a record out of the history. Now a store runs one git command at a time.
- **Doctor check.** The new `records_git` check reads the records repository without writing or locking (`GIT_OPTIONAL_LOCKS=0`). It reports an `index.lock` older than `records.git_lock_stale_minutes` (default 10) as FAIL. It warns on more uncommitted paths than `records.git_uncommitted_warn_paths` (default 50), and on a last commit at least `records.git_last_commit_warn_hours` (default 24) old while paths are uncommitted. Nothing removes a lock.
- **Root cause.** A lock that stays is not traced to one cause by the code: it is a timeout kill or a termination from outside.
- **Config and contract.** Three config fields. The contract is `prompts/bf-957-records-git-signal.md`.

```

**P3-2.** `DECISIONS.md`. The convention is to append after the newest Era V entry, which is the AD-1358 S1 entry ending at `:1488`. Its last bullet occurs once in the file.
SEARCH:
```
- *Reversal.* Revert the AD-1358 S1 commits.
```
REPLACE:
```
- *Reversal.* Revert the AD-1358 S1 commits.

### BF-957 -- Ship's Records says when git fails, and probos doctor reports a stopped records history (DATE, #1760)

- *Scope.* `knowledge/records_store.py` (`_git_sync`, `_commit`, `_warn_git_once`, `_forget_git_warnings`, `_git_error_line`, a per-store git lock), `doctor/checks/records_git_check.py` (new), `doctor/checks/__init__.py`, `config_models/knowledge.py` (three `RecordsConfig` thresholds), the config facade baseline and reference (regenerated), two guard tables, tests. Contract `prompts/bf-957-records-git-signal.md`.
- *G1 (cause).* The code proves one defect and cannot choose the cause of a stale lock. `_commit_lock` covered `git commit` only, so the store's `git add` calls overlapped its other git commands in executor threads. The loser failed with git's lock message and its path was left out of the history, but it left no lock. A lock that stays needs a git process that ended without its cleanup: the `subprocess.run` timeout kill (TerminateProcess or SIGKILL) or a termination from outside. Chosen: one git child per store at a time, and a WARNING when the timeout stops a command. Deferred: not killing on timeout (trigger: that WARNING in a log). Rejected: a lock pre-check (a race; git already refuses), a longer timeout (no evidence for a value).
- *G2 (signal).* WARNING once per (verb, first output line) until a git add or commit succeeds; 32 remembered, oldest dropped; nothing-staged commits are not errors; return values and raised exceptions unchanged.
- *G3 (doctor).* `records_git` after `disk`: a lock at least `git_lock_stale_minutes` old is FAIL; uncommitted paths over `git_uncommitted_warn_paths`, and a last commit at least `git_last_commit_warn_hours` old with uncommitted paths, are WARN. Read-only: stat, and git with `GIT_OPTIONAL_LOCKS=0`.
- *G4 (removal).* No automatic removal of a lock. The log and the doctor say that removing one is the operator's decision.
- *Not changed.* The 30 s timeout, the write paths and their return values, `KnowledgeStore`, `config/system.yaml`.
- *Residual.* Recorded limits L1 to L11 of the contract.
- *Reversal.* Revert the BF-957 commits.
```

**Ledger.** G3. The roadmap Bug Tracker is not edited: it holds no BF-95x row (`rg "BF-95[0-9]" docs/development/roadmap.md` finds 0), and BF-952 did not add one.

## 8. What this does NOT change

- The 30 s timeout and the kill on timeout.
- What `_git_sync` returns, and what it and `_commit` raise, except that git's output is decoded as UTF-8 (A4, §7.2c). `get_history` runs one `git log` with UTF-8 output, and every `git commit` the store runs pins `i18n.commitEncoding=UTF-8` (A7, §7.2f); no other command's argv changes.
- The six write paths.
- `KnowledgeStore` (`store.py`).
- `probos reset`'s git calls (`__main__.py:3183-3193`).
- `config/system.yaml`.
- Any live repository. Nothing removes `index.lock`.

## 9. Mutation rows (each Line occurs once in its file on M2's head)

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| R-1 | records_store.py | `            with self._git_lock:` (A4: inside the outer `try`) | `            if True:` | T7 |
| R-2 | records_store.py | `            if key in self._git_warned:` (A4: in `_remember_git_warning`) | `            if False:` | T2 |
| R-3 | records_store.py | `            if len(self._git_warned) >= _GIT_WARNED_MAX:` | `            if False:` | T4 |
| R-4 | records_store.py | `                    if verb in _GIT_INDEX_VERBS:` (A4 indentation) | `                    if False:` | T3 "an add succeeds" |
| R-5 | records_store.py | `_GIT_NOTHING_STAGED = ("nothing to commit", "nothing added to commit")` | `_GIT_NOTHING_STAGED = ("nothing to commit",)` | T8 untracked |
| R-6 | records_store.py | `                except subprocess.TimeoutExpired:` (A4 indentation) | `                except ValueError:` | T5 |
| R-7 | records_store.py | `                return line.strip()[:300]` | `                return "fatal"` | T2 |
| R-8 | records_store.py | `                    ("commit", type(e).__name__),` | `                    ("commit", str(id(e))),` | T6 |
| R-9 | records_store.py | `_GIT_INDEX_VERBS = frozenset({"add", "commit"})` | `_GIT_INDEX_VERBS = frozenset({"add", "commit", "rev-list"})` | T3 "a read succeeds" |
| D-1 | records_git_check.py | `    if age_min >= records.git_lock_stale_minutes:` | `    if age_min >= 0:` | DC2 (9 min) |
| D-2 | records_git_check.py | `    if pending > records.git_uncommitted_warn_paths:` | `>=` | DC3 (bound 3) |
| D-3 | records_git_check.py | `    if pending and age_h >= records.git_last_commit_warn_hours:` | `    if age_h >= records.git_last_commit_warn_hours:` | DC4 (clean) |
| D-4 | records_git_check.py | `        env={**trusted_command_env(), "GIT_OPTIONAL_LOCKS": "0"},` | `        env=trusted_command_env(),` | DC8 (sets an ambient `GIT_OPTIONAL_LOCKS=1` first, so the mutant passes `"1"` through on any host, including one that exports `0`) |
| D-5 | records_git_check.py | `        if not records.auto_commit:` | `        if False:` | DC5 auto_commit off |
| D-6 | checks/__init__.py | `    records_git_check,  # BF-957: after disk, before federation` | delete | DC1 |
| R-10 | records_store.py | `                if isinstance(e, subprocess.TimeoutExpired):` | `                if False:` | T10 |
| R-11 | records_store.py | `                        error,  # BF-957 A3: git's first line only; the rest may advise removing a lock without the precondition` | `                        result.stderr,` | T11 |
| R-12 | records_store.py | `                # BF-957 A3: classified under the lock, so a later child's warning is never cleared by an earlier success.` | delete it and dedent every following line of the `with self._git_lock:` block, through its last `return result.stdout`, by four spaces (classification after the release, still inside the outer `try`) | T12 "success", "failure" |
| D-7 | records_git_check.py | `            repo.lstat()  # BF-957 A4: an entry exists even when it is a link whose target is missing` | `            repo.stat()` | DC6 "a broken link" (`stat` follows the link and raises `FileNotFoundError`; a junction on Windows, killed in A4's campaign; a symlink elsewhere) |
| D-8 | records_git_check.py | `        ["git", *HARDENED_GIT_CONFIG_ARGS, "-C", str(repo), *args],  # BF-957 A3: optional locks do not stop an fsmonitor` | `        ["git", "-C", str(repo), *args],` | DC9 (`_hermetic_git` sets `GIT_CONFIG_COUNT=0` first, so a host that exports `core.fsmonitor=false` cannot hide the mutant) |
| R-13 | records_store.py | `                if self._remember_git_warning((verb, error)):` | `                if self._warn_git_once((verb, error), "bf957 mutant"):` (logs under the lock, the A3 shape) | T12 "failure" |
| R-14 | records_store.py | `                    if self._remember_git_warning((verb, "timeout")):` | `                    if self._warn_git_once((verb, "timeout"), "bf957 mutant"):` | T12 "timeout" |
| R-15 | records_store.py | `                        encoding="utf-8",  # BF-957 A4: the locale's codec (cp1252) lost output; A5: see get_history` | `                        text=True,` | T13 |
| R-16 | records_store.py | `                    "Ship's Records: git commit raised %s: %s. The record is written to disk; whether it reached "` | `                    "Ship's Records: git commit did not run (%s: %s). The record is written to disk; whether it reached "` | T6 |
| D-9 | records_git_check.py | `        if not repo.is_dir():` | `        if False:` | DC6 "a file", "a broken link" |
| R-17 | records_store.py | `                "--encoding=UTF-8", "--format=%H%x00%aI%x00%s",  # BF-957 A5, A7: one read, UTF-8 output` | `                "--format=%H%x00%aI%x00%s",` | T14 "logOutputEncoding" |
| R-22 | records_store.py | `        pin = ("-c", "i18n.commitEncoding=UTF-8") if verb == "commit" else ()` | `        pin = ()` | T14 "commitEncoding", "both", "commitEncoding after the first" (the label premise); T16 "commitEncoding", "both" (derived) |
| D-10 | records_git_check.py | the three lines `        try:`, `            repo.lstat()  # BF-957 A4: ...`, `        except FileNotFoundError:` before the "does not exist yet" result | `        if not repo.exists() and not repo.is_symlink():` (A3's shape) | DC6 "a broken link", on Windows only (a junction); on POSIX it survives by construction |
| H-1 | test_bf957_records_git_signal.py | `        if name.upper().startswith("GIT_"):` | `        if name.upper() in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_CONFIG_PARAMETERS"):` (A4's list) | TI |

There is no campaign of record yet; the Builder runs the mutants on M2's head.

## 10. Recorded limits

- **L1.** The root cause of a lock that stays is not established. The 30 s value and the kill are unchanged. The timeout WARNING is what tells the next occurrence apart.
- **L2.** The store's lock is per instance and per process. Git from outside (an operator shell, an IDE, a backup) is not serialized with it.
- **L3.** The nothing-staged exemption matches git's English messages, as the base did. Under a localized git, such a commit is logged once until an add or commit succeeds.
- **L4.** The once-per-error memory is lost on restart. A lasting error is logged once per start.
- **L5.** Whether `git commit` itself fails on a stale lock or reports nothing staged depends on git's version. The tests assert only the `add`.
- **L6.** Queued git calls occupy default-executor threads while they wait: no more threads than before, but each is held longer.
- **L7.** `trusted_command_env()` passes the operator's `GIT_*` variables (for example `GIT_DIR`) through, as for the store.
- **L8.** A path whose `git add` failed stays out of the history until a later `git add` stages it: a write of the same path, or the dream cycle's notebook consolidation, which runs `git add -A` on the store when it archives an entry (`cognitive/dreaming.py:1027`; `notebook_consolidation_enabled` defaults to true). The next write's commit then records it; a vessel that writes nothing after the failure does not. (A3 corrects the earlier text, which named only a write of the same path.) Re-adding everything (`git add -A`) is the Captain's recovery step in #1760, not this BF.
- **L9.** The uncommitted count includes any file in the repository, including files ProbOS did not write.
- **L10.** A `.git` that is a file (gitfile) is reported as "not a git repository".
- **L11.** The signal is the log plus `probos doctor` when the operator runs it. A runtime alert was considered and deferred.
- **L12.** (A3, review round 1 finding 1; narrowed by A4, round 2 finding 6.) A logging handler whose `emit` raises propagates out of `_git_sync` or `_commit` into the write that called it, and on the timeout path it replaces the `TimeoutExpired`. Python's handlers report many of their errors through `handleError`, but not all: the round-2 reviewer ran a `logging.FileHandler(delay=True)` whose directory was missing, and its `emit` raised `FileNotFoundError` with no `handleError` call. ProbOS's one custom handler (`_BootWarningCounter`, `__main__.py:107`) only counts. A guard would be a swallow-tier `except` around a log call, against property 1, and every log call on every write path has the same exposure. A raising sink is a logging-setup defect, recorded for logging-setup follow-up. (A4, qualified by A5) A handler that blocks rather than raises no longer runs while its own `_git_sync` call holds `_git_lock`: that call emits after releasing it. Another thread's command may still hold the lock (L14).
- **L13.** (A4) The check tests the records path with `lstat` and `.git` with `is_dir`. A `.git` that is a link whose target is missing reads as "not a git repository" (WARN), as a gitfile does (L10); what startup's `git init` then does is not measured. On Windows, a path below a regular file may read as absent (OK) while startup cannot create it; not measured. An `index.lock` that is a link whose target is missing reads as "none"; git creates its lock as a regular file, not a link.
- **L14.** (A5, round-3 R3-4.) `_git_sync` logs after its own call releases `_git_lock`, but another thread's git command may hold the lock by then, so a log handler that reads git through the store waits for that command. The round-3 reviewer observed this (`owner='second', emitter='first'`; both completed). How long the wait can last was not measured.
- **L15.** (A5, round-3 R3-1; A6; rewritten by A7.) `get_history` runs one `git log` with `--encoding=UTF-8`. Git outputs an unlabelled commit's subject as stored, whatever an operator's `i18n.logOutputEncoding` (T14), and converts a labelled commit's subject from its label (measured for ISO-8859-1 and Shift_JIS, including ISO-8859-1 bytes that are also UTF-8: T15). For a label git cannot convert from (a pipe, a carriage return, an unknown name, `none`, a 300-character name) it outputs the bytes as stored (T15; probe P-G2). Every `git commit` the store runs pins `i18n.commitEncoding=UTF-8`, so the store's commits carry no label (T14). Residuals: (1) a commit an older store wrote under an operator's `i18n.commitEncoding` holds UTF-8 under another label and reads as git converts it (`café` as `cafÃ©` under CP1252). With a cp1252 decoder the base reads it the same or worse (probe P-G5). With a UTF-8 decoder the base read a commit labelled CP1252, or with an empty label, right when a read-time `i18n.logOutputEncoding` or `i18n.commitEncoding` was CP1252 (git then outputs the stored bytes), and wrong with no setting; A7 reads it wrong in all three settings. This is a regression against the base on a configured host (round-5 finding 1, recorded under the round-four brake; #1754). A6 read the CP1252 and ISO-8859-1 labels right, not the empty label. Nothing tells it apart from a commit correctly stored in that label. (2) From A4 on, an unlabelled commit whose bytes are not UTF-8, which only a tool other than `git commit` writes, reads with replacement characters, and so does a commit under a label git cannot convert from whose stored bytes are not UTF-8: git outputs them as stored whatever the output encoding (probe P-G8). With a cp1252 decoder the base read Latin-1 bytes right in both cases (measured in round 5). With a UTF-8 decoder the base returned no rows for the unconvertible label, and A7 returns them with replacement characters (P-G8). Round-5 finding 2, recorded under the round-four brake; the bytes-level read is the follow-up in #1754. (3) From A4 on, the store's own messages on a POSIX host whose locale is not UTF-8, where Python passes the arguments to git in that locale's encoding. Not measured.
- **L16.** (A7, round-4 F5; pre-existing.) `_git_sync` decodes in text mode, which turns a carriage return into a line break, so `get_history` cuts a subject at a carriage return it holds (the base and every amendment alike; measured by the orchestrator). Git's whitespace cleanup removes a carriage return at a line end, so only one inside a line reaches a subject (the Architect derived this; the orchestrator measured it with `git commit -m` and `-F`: `a<CR>` is stored as `a`, `a<CR>b` keeps its carriage return and `a<CR><LF>b` is stored as two lines). A bytes-level read is recorded as a follow-up in #1754.

## 11. Verified Against Codebase (2026-11-06, tree `baea653d`)

```
rg -n "_git_sync|_commit\b|subprocess|logger\.|Lock\(|run_in_executor" src/probos/knowledge/records_store.py
  9: import subprocess
  521: self._commit_lock = asyncio.Lock()
  1619-1622: async def _git ... loop.run_in_executor(None, self._git_sync, args)
  1624-1637: def _git_sync ... subprocess.run(... timeout=30) ... logger.debug("git %s stderr: %s", ...)
  1639-1647: async def _commit ... async with self._commit_lock ... logger.debug("Git commit skipped: %s", e)
rg -n "_git\(|_commit\(" src/probos/knowledge/records_store.py   (with -B1)
  542, 544, 545, 548, 549, 675, 794, 896, 1379, 1418, 1492, 1545, 1570, 1645  -> 14 sites
  674/793/895/1417/1544/1569: if self._config.auto_commit:
Read records_store.py:1375-1397 (get_history try/except -> []) and :1488-1496 (get_stats try/except -> 0)
rg "TimeoutExpired|threading" src/probos/knowledge/records_store.py   -> 0 (absence: both new)
rg -n "RecordsStore\(" src/probos   -> cognitive_services.py:609, __main__.py:3285, __main__.py:3574
Read cognitive_services.py:598-619 (resolver, initialize, except -> warning, records disabled)
Read config.py:2658-2666 resolve_records_repo_path
Read config_models/knowledge.py:317-355 RecordsConfig (auto_commit :322, semantic_index_enabled :355); :10 imports Field
Read doctor/registry.py:21-38, doctor/protocol.py:22-77 (CheckResult.detail, DoctorContext), checks/__init__.py:9-35
Read doctor/checks/disk_check.py, data_dir_check.py, chroma_check.py (shape); rg ctx.config is None (command_policy WARN pattern)
rg -n "subprocess|trusted_command_env" src/probos/doctor   -> sandbox_check.py only
Read tests/test_bf892_spawn_env_guard.py:82-104 (TRUSTED_ENV_SITES; :96 sandbox row), :382-398 (dict env must start with **trusted_command_env())
Read tests/fixtures/ad1346_effect_census.py:56 (OUTSIDE_RUNTIME includes src/probos/doctor/), :143, :150
rg iter_checks tests -> positional pins only: extras+1 (ad1327:912, ad1328_s2a:705, bf906:350, bf901:458), crew_enrollment+1, token_accounting+1 (bf917:631-632)
Read tests/test_ad1270e2f_knowledge_models.py:212-239 (RecordsConfig dump), :364-374 (baseline fields), :456-480 (bound counts, RecordsConfig: 0)
Read tests/test_ad1270e1_config_facade.py:1569-1574 (field_definitions == 1883)
git show --stat d80c6f12 -> precedent: baseline + config-reference regenerated, e1 count and e2c dump edited for appended fields
Read docs/development/config-facade-baseline.yaml:3023-3057 (RecordsConfig block)
rg description scripts/gen_config_reference.py -> :164 renders Field(description)
rg RecordsStore docs/development/architecture-baseline.yaml -> :751 (already a baseline row); SRP_MAX_DIRECT_METHODS = 15
Read knowledge/store.py:1105-1239 (KnowledgeStore logs git failures at WARNING; in-place index/ref repair)
Read __main__.py:3180-3195 (reset git, its own repo_path)
Read PROGRESS.md:1-5; rg DECISIONS.md headings: AD-1358 S1 at :1477, its Reversal bullet at :1488 (once)
rg "BF-95[0-9]" docs/development/roadmap.md -> 0
git show --stat 48ed13bf -> BF-952 updated ad-ledger-snapshot.json and open-ads-report.md (G3)
```

**Not measured.** The `--collect-only` counts: pytest is not allowed under the bridge. M0 records them.

## 12. Prior Art and Blind Spots

- **Internal: adopted.** `KnowledgeStore._git_commit` (`store.py:1105-1202`) logs add and commit failures at WARNING; this contract adopts that level.
- **Internal: rejected.** The same function repairs the index and refs in place by deleting files. Rejected under decision 4.
- **External, from search summaries only** (the git mailing-list patch page refused the fetch):
  - A process killed with SIGKILL leaves `index.lock`, and later git commands fail (JENKINS-12513; a Claude Code issue on SIGKILL orphaning `index.lock`).
  - On Windows, git's signal handlers may not run when a git process is terminated, which leaves a lock that Linux would not (a Git for Windows "kill child processes in a gentler way" patch).
  - Mux and Zuul remove old lock files automatically. **Rejected:** decision 4. Proving that no process holds the lock is a race across processes.
- **`GIT_OPTIONAL_LOCKS=0`.** From git(1); not re-fetched here.
- **`reference-projects.md`** (judged on 2026-11-06). None of its rows concerns git repository maintenance. No row was examined and none is updated.
- **Blind spots handled.**
  - The store contending with itself produced the same error text as a stale lock. Serialization separates them.
  - A git commit with untracked files present says "nothing added to commit". It is exempted.
  - The doctor's own `git status` could take a lock, or be stopped while holding one. Optional locks are off. A configured fsmonitor still runs with optional locks off; A3 adds `HARDENED_GIT_CONFIG_ARGS` (review round 1 found it).
  - An idle vessel with a clean tree is not flagged for an old last commit.
- **Blind spots recorded.** L3 (localized git), L8 (paths lost by a failed add), L11 (no runtime alert).

## 13. Diff Reviewer: properties to verify

1. On every path that does not raise, `_git_sync` returns `result.stdout`, decoded (A4) as UTF-8 with replacement, so it is always a `str`. It raises what the base raised, re-raising the same `TimeoutExpired` object, except a decode error, which can no longer occur (A4), and it has no new `except` for any other exception. A logging handler that raises is out of scope (L12).
2. Within one store, no git child starts while another is running. `_git_lock` is never held across an `await` and never taken on the event-loop thread. `_commit_lock` is still taken before `_git_lock`, never after it. (A4, qualified by A5) `_git_sync` emits no log record while its own call holds `_git_lock`: it decides under the lock and logs in a `finally` after releasing it, on the timeout path too. Another thread's command may hold the lock at that moment, so a handler that reads git through the store can wait for that command (L14); it does not wait on the emitting call.
3. A given key is logged at most once between successful `add` or `commit` exits. `_git_warned` never exceeds 32 keys and is touched only under `_git_warned_lock`. A successful read clears nothing. (A3, A4) In `_git_sync`, the result is classified and the memory is changed (`_remember_git_warning`, `_forget_git_warnings`) while `_git_lock` is still held, so it changes in the order the children ran. `_commit` updates the memory and logs on the event-loop thread without `_git_lock` (property 2 forbids taking it there), for any `Exception` other than a timeout, without a claim about where it came from; a timeout that reaches `_commit` is not logged again, and cancellation propagates, as before.
4. A non-zero commit whose stdout says "nothing to commit" or "nothing added to commit" logs nothing.
5. Nothing in `records_git_check.py` writes, renames or deletes a path. Every git launch in it carries `GIT_OPTIONAL_LOCKS=0` and (A3) starts with `HARDENED_GIT_CONFIG_ARGS`, so a configured fsmonitor or hook does not run; DC9 proves this with a recursive snapshot. A records path that exists and is not a directory is FAIL, not OK. (A4) "Exists" means `lstat` succeeds, so a link whose target is missing exists.
6. The check obtains the repository only through `resolve_records_repo_path(ctx.config.records, ctx.data_dir)`.
7. The three fields have the stated defaults, bounds and descriptions. A zero-config `SystemConfig()` loads.
8. Each guard-table row names a function with exactly one launch. The census row is `OutsideRuntime` under `src/probos/doctor/`. The bound table moves by exactly RecordsConfig +3 (sum 21 to 24). The census moves by exactly OutsideRuntime +1 and launches +1 (39 to 40).
9. No code under `src/` deletes `index.lock`. The messages give no instruction to delete without the stated precondition. (A3) The failure WARNING carries git's first output line only, so git's own "remove the file manually" advice is not logged.
10. At M1, each xfail case fails at an `AssertionError`.
11. (A3) No message says a timed-out command did not run or did not reach the history. The timeout WARNING says what it changed is not known, and `_commit` adds no second warning for it. (A4) `_commit`'s warning for any other exception says whether the commit reached the history is not known.

## 14. Acceptance criteria

- G1, G2 and G3 as stated. The broad gate is green with a receipt.
- T1 crosses the seam: lock → store write → WARNING → doctor FAIL → nothing written.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06: Amendment A1 (§7.2a): P2-11 (the only inline pair, which the oracle's apply tool skipped) is replaced by the fenced A1-1, and the aggregate pins the contract left out are added (A1-2 to A1-5: the bound table's comment, docstring, sum and sorted list, and the effect census's `OutsideRuntime` and launch totals).
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07: Amendment A2: DC8 now sets an ambient `GIT_OPTIONAL_LOCKS=1` before it reads, and row D-4 says so. The orchestrator's mutation rehearsal found that D-4 survived on a host that already exports `GIT_OPTIONAL_LOCKS=0`, where the test passed without testing anything.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07: Amendment A3 (§7.2b), review round 1. Findings 2 to 7 fixed (fsmonitor, a file at the repo path, warning order under the git lock, timeout wording and double log, git's first line only, L8). Finding 1 recorded as L12. New tests T10, T11, T12, DC9, and DC6 "a file"; new mutation rows R-10 to R-12, D-7 and D-8; R-4 re-indented.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07: Amendment A4 (§7.2c), review round 2. F1 UTF-8 decoding folded in; F2 `lstat` absence; F3 `_hermetic_git`; F4 log emitted after `_git_lock` is released; F5 and F6 text corrected; L13 added. New test T13 and DC6 "a broken link"; T6 and T12 changed; rows R-13 to R-16 and D-9 new; R-1, R-4, R-6, R-11, R-12, D-7 and D-8 rewritten.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07: Amendment A5 (§7.2d), review round 3 (round-three brake: continue). R3-1 `get_history` reads each subject in its commit's own encoding label; R3-2 `_isolate_git` removes every `GIT_*` variable; R3-3 DC6 builds a junction on Windows; R3-4 the lock-wait sentences qualified; L13 corrected; L14 and L15 added. New tests T14 and TI; rows R-17 to R-19, D-10 and H-1 new; R-15 and D-7 rewritten.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07: Amendment A6 (§7.2e), before review round 4. The orchestrator's matrix showed A5 misread commits stored in their labelled encoding: the second read's text now replaces the first only when it is valid UTF-8; fields are separated by NUL. L15 rewritten. New test T15; rows R-20 and R-21 new; R-17 and R-18 rewritten.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07: Amendment A7 (§7.2f), review round 4 (round-four brake: continue). The store's `git commit` pins `i18n.commitEncoding=UTF-8` and `get_history` returns to one `git log --encoding=UTF-8`: F1, F2 and F3 closed by construction, F4 annotated, F5 recorded as L16. L15 rewritten. T14's premise rewritten; T15 gains two cases, a launch count and `limit=1`; new test T16; rows R-18 to R-21 deleted, R-17 rewritten, R-22 new.
