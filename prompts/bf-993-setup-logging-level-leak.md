# BF-993: tests that run the boot logging setup put back the logger levels it pins; the AD-1337 reflect tests name the decomposer logger they read

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24 (consult 91af63b3, read-only): the design, pairs P1-1 to P1-9, the stressor and mutation rows, the tracker texts, the reviewer properties and the #1523 text.
**Assembled by:** the orchestrator, 2026-11-24: the section 6 headings and the pair layout follow what `contract_tools.py` reads; sections 1, 7, 8.1, 8.2, 10, 11, 13, 14 and 15, the measured results, the pin plugin file of 8.3 and rows M4b and M6 are the orchestrator's; section 13 lists every place where the pairs or the Architect's texts differ from the consult.
**Status:** ready to build. **Owning issue:** #1815 (a further slice of its batch; this slice has a review of its own). It also records the flake on #1523. Commits say `Refs #1815, #1523.`
**Base:** `b428497b` (the head of the BF-981 part 2 slices). `origin/main` is `542a2a68` and is already merged: `git log HEAD..origin/main` is empty. **Number:** BF-993 (allocated 2026-11-24 from the enumeration in section 10; BF-992 stays with #1324).
**Line endings:** the working copies are CRLF and the blocks below are LF; the orchestrator matches them after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 3 new (`tests/test_bf993_logger_level_leak.py`), 0 removed, 0 changed.
**Scope:** test files and trackers. No file under `src/` or `scripts/`, and no pytest or CI configuration, changes.

## 1. Problem (premise table)

| Test | Recorded failure | The premise it assumes |
|---|---|---|
| `tests/test_ad1337_reflect_route.py:114` `test_every_form_in_a_node_result_is_masked_before_the_model_and_the_log` | Canonical gates `bf-981-1815-w3` and `bf-981-1815-w3b` of `b428497b` (2026-11-24, 3 workers, no receipt): `1 failed, 54755 passed, 184 skipped`, `ValueError: not enough values to unpack (expected 1, got 0)` at `:133`, the same test at the same 92% mark; it ran on `gw0` in the first gate and on `gw1` in the second | `caplog.set_level(logging.DEBUG)` (the root logger) is enough to capture the decomposer's DEBUG record `Reflect prompt` (`decomposer.py:501`). It is not once any earlier test of the process has run `_setup_logging`, which pins `probos.cognitive.decomposer` and ten more loggers at WARNING for the life of the process (`__main__.py:187-197`): a record whose own logger has a level is judged against that level, not the root's |
| same file, `:172` `test_a_failed_pass_makes_no_reflect_call` | none recorded (it passes under a pin) | The absence check at `:189` (no `Reflect prompt` record) is a real check. Under a pin the record cannot exist, so the check is vacuous |
| `tests/test_bf875_mcp_inbound_auth.py:396` `test_door_a_refusal_logs_no_token` and `tests/test_bf876_a2a_inbound_auth.py:439` `test_door_refusal_logs_no_token` | none recorded in a gate; each fails once in row S4 on the base (section 8.3) | `caplog.at_level(logging.DEBUG)` (the root logger) captures the `BF-875` and `BF-876` records (`:403`, `:447`) that `probos.federation.*` loggers emit. `probos.federation` is one of the eleven pinned loggers |
| Polluters: `tests/test_ad1026_boot_verbosity.py` `_logger_state` (`:29-52`; the tests that call `_setup_logging` at `:134`, `:143`, `:152`, `:162`, `:206`, `:216`) and `tests/test_bf748_file_log_carries_the_date.py` `_handlers` (`:25-40`, called by the module-scoped `rendered` fixture) | n/a | Restoring the root logger's handlers (and, in ad1026, its level) undoes what `_setup_logging` changed. It does not: the eleven named levels stay |

Measured on the base `b428497b` (section 8.3): one process with either polluter file first fails the victim at `:133` (rows S1, S2); a session that pins the decomposer logger and runs the victim file alone fails it (row S3); the victim file alone passes (S3's other nine cases pass under the pin, and so do its `:217`-`:234` tests, which read records from loggers that are not pinned).

## 2. Overview

- **Close the leak at its two sources.** One helper, `tests/fixtures/logger_levels.py::restored_logger_levels()`, snapshots the level of every named logger and puts back each that changed. `_logger_state` (ad1026) wraps its `yield` in it and `_handlers` (bf748) wraps its `_setup_logging` call in it.
- **Make the observed victim independent.** The two reflect tests name `probos.cognitive.decomposer` in `caplog.set_level`, so they do not depend on the process's logger state. That also makes the second test's absence check real under a pin.
- **Prove the repair.** `tests/test_bf993_logger_level_leak.py` (3 tests): the file-log helper leaves the pinned loggers as it found them; the helper puts back a changed level and leaves a logger created inside at NOTSET; the helper puts levels back when the block raises.
- **Trackers.** `PROGRESS.md` and `DECISIONS.md`, then `gen_ad_ledger.py`.

Rejected, one line each (the Architect's):
- A `conftest.py` autouse restore for every test: it walks the logger registry for all 54,940 tests, hides future leaks across the whole suite and changes a shared contract. The leak has two sources.
- A change in `_setup_logging`: its pins are right for the CLI. No production change.
- Edits in the bf875 and bf876 tests: closing the leak at its sources covers them (row S4).
- A list of the eleven names in each fixture: a twelfth pin would be missed.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | One shared helper puts back every named logger's level; it only calls `setLevel` for a logger whose level changed | A list of names goes stale when `_setup_logging` gains a pin. Every `setLevel` clears the cache of every logger, so unchanged loggers are left alone |
| D2 | A logger created inside the block goes back to NOTSET, its default | A logger the block made cannot have had a level to put back, and a pin on it must not outlive the block |
| D3 | The two reflect tests name the decomposer logger; `:217` and `:234` stay | Those two read records from `probos.consensus.escalation` and `probos.security.secret_masking`, which are not pinned and are not children of a pinned logger |
| D4 | The two latent victims (bf875, bf876) are not edited | D1 covers them; row S4 shows it |
| D5 | BF-993, on this branch, reviewed as its own slice from round 1, then the batch's ONE canonical gate at 3 workers on the final head | The BF-981 part 2 rounds (three, approved) stay valid: BF-993 touches none of their files. Runs 3 and 4 wrote no receipt, so the next gate is the only gate evidence that counts |
| D6 | The first new test also puts back the root level it changes (orchestrator, section 13) | `_handlers` calls `_setup_logging`, which sets the root level, and has never put it back; a new test must not add a second place that leaves it changed |

## 4. Milestones and commits

The Builder applies the pairs only. The orchestrator commits by plumbing. No subject carries an `AD-` or `BF-` token, and no commit text uses the words close, fix or resolve.

- **M1** (S1): P1-1 to P1-9, in `tests/fixtures/logger_levels.py` (new), `tests/test_bf748_file_log_carries_the_date.py`, `tests/test_ad1026_boot_verbosity.py`, `tests/test_ad1337_reflect_route.py` and `tests/test_bf993_logger_level_leak.py` (new). Subject: `Tests that run the boot logging setup put back the logger levels it pins`
- **M2** (trackers): P2-1 and P2-2, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `Trackers for the logger level leak repair`

M1 and M2 may be one Builder delegation (about 25 tool calls).

**Risk:** Low (test and docs only); the helper is a new module that only the new and edited tests import. None is a shared contract.

**Order and review:** M1, then M2. One Diff Reviewer pass covers both (the delta over `b428497b`).

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py` (M2), and run `git diff --check` and `git diff --stat`.
- **May not:** run pytest, commit, edit an unnamed file, add `skip`/`xfail`/a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `tests/fixtures/logger_levels.py` (new file, M1)

**P1-1** The file text, in full:

```python
"""BF-993: put back every named logger's level that a block changed.

``probos.__main__._setup_logging`` pins eleven named loggers at WARNING for the life
of the process (src/probos/__main__.py:187-197). A test that calls it and restores only
the root logger leaves them pinned, and a later test in the same worker that captures
DEBUG or INFO through the root logger alone loses those loggers' records and their
children's (#1523, #1815).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def restored_logger_levels() -> Iterator[None]:
    """Snapshot every named logger's level; on exit set back each that changed.

    A logger created inside the block goes back to NOTSET, its default.
    """
    manager = logging.Logger.manager
    saved = {
        name: logger.level
        for name, logger in list(manager.loggerDict.items())
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        for name, logger in list(manager.loggerDict.items()):
            if not isinstance(logger, logging.Logger):
                continue
            level = saved.get(name, logging.NOTSET)
            if logger.level != level:  # setLevel clears every logger's cache
                logger.setLevel(level)
```

### 6.2 `tests/test_bf748_file_log_carries_the_date.py` (M1)

**P1-2** (the import block, `:16-19`)
SEARCH:
```python
import logging
import re

import pytest
```
REPLACE:
```python
import logging
import re

import pytest

from tests.fixtures.logger_levels import restored_logger_levels
```

**P1-3** (`_handlers`, `:29-40`)
SEARCH:
```python
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    try:
        _setup_logging("INFO", verbose=False)
        return tuple(root.handlers)
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
```
REPLACE:
```python
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    try:
        # BF-993: _setup_logging pins eleven named loggers at WARNING; put them back.
        with restored_logger_levels():
            _setup_logging("INFO", verbose=False)
            return tuple(root.handlers)
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
```

### 6.3 `tests/test_ad1026_boot_verbosity.py` (M1)

**P1-4** (the module docstring, `:10-13`)
SEARCH:
```python
logging boundary). ``_setup_logging`` mutates the global root logger, so every
test that calls it runs under the ``_logger_state`` fixture which snapshots and
restores the root logger's handlers + level and closes any file handler the
call opened (FD hygiene).
```
REPLACE:
```python
logging boundary). ``_setup_logging`` mutates the global root logger, so every
test that calls it runs under the ``_logger_state`` fixture which snapshots and
restores the root logger's handlers + level, every named logger's level (BF-993),
and closes any file handler the call opened (FD hygiene).
```

**P1-5** (the imports, `:22-24`)
SEARCH:
```python
import pytest

import probos.__main__ as m
```
REPLACE:
```python
import pytest

import probos.__main__ as m
from tests.fixtures.logger_levels import restored_logger_levels
```

**P1-6** (`_logger_state`, `:32-43`)
SEARCH:
```python
    """Snapshot/restore the root logger's handlers + level around a test.

    ``_setup_logging`` adds console/file/counter handlers to the global root
    logger and pins per-logger levels. Without restoration these leak across
    tests and the file handler accumulates open descriptors. We restore the
    handler list + level and close any file handler the test opened.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
```
REPLACE:
```python
    """Snapshot/restore the root logger's handlers + level and every logger's level.

    ``_setup_logging`` adds console/file/counter handlers to the global root
    logger and pins per-logger levels. Without restoration these leak across
    tests and the file handler accumulates open descriptors. We restore the
    handler list + level, every named logger's level (BF-993), and close any
    file handler the test opened.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        with restored_logger_levels():
            yield
```

### 6.4 `tests/test_ad1337_reflect_route.py` (M1)

**P1-7** (`:114-118`)
SEARCH:
```python
async def test_every_form_in_a_node_result_is_masked_before_the_model_and_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    decomposer, llm = _decomposer(_real_masker(tmp_path, github=VALUE))
```
REPLACE:
```python
async def test_every_form_in_a_node_result_is_masked_before_the_model_and_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    # BF-993: the decomposer's own level, so a logger pinned earlier in the process cannot drop the record.
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.decomposer")
    decomposer, llm = _decomposer(_real_masker(tmp_path, github=VALUE))
```

**P1-8** (`:172-176`)
SEARCH:
```python
async def test_a_failed_pass_makes_no_reflect_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    decomposer, llm = _decomposer(_real_masker(tmp_path, github=VALUE))
```
REPLACE:
```python
async def test_a_failed_pass_makes_no_reflect_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    # BF-993: without it a pinned decomposer logger makes the absence checks below vacuous.
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.decomposer")
    decomposer, llm = _decomposer(_real_masker(tmp_path, github=VALUE))
```

### 6.5 `tests/test_bf993_logger_level_leak.py` (new file, M1)

**P1-9** The file text, in full:

```python
"""BF-993 (#1523, #1815): calling _setup_logging in a test leaves no logger pinned."""

from __future__ import annotations

import logging
import uuid

import pytest

from tests.fixtures.logger_levels import restored_logger_levels
from tests.test_bf748_file_log_carries_the_date import _handlers

PINNED = (  # src/probos/__main__.py:187-197
    "asyncio", "aiosqlite", "httpx", "httpcore", "probos.substrate.agent",
    "probos.federation", "probos.cognitive.decomposer", "probos.mesh.intent",
    "probos.mesh.routing", "probos.substrate.spawner", "probos.substrate.pool",
)


def test_the_file_log_helper_leaves_the_pinned_loggers_as_it_found_them() -> None:
    root = logging.getLogger()
    root_level = root.level  # _setup_logging sets it; _handlers does not put it back
    try:
        with restored_logger_levels():
            for name in PINNED:
                logging.getLogger(name).setLevel(logging.NOTSET)
            for handler in _handlers():
                if isinstance(handler, logging.FileHandler):
                    handler.close()
            assert {name: logging.getLogger(name).level for name in PINNED} == dict.fromkeys(
                PINNED, logging.NOTSET,
            )
    finally:
        root.setLevel(root_level)


def test_a_level_set_inside_is_put_back_and_a_logger_made_inside_is_left_notset() -> None:
    existing = logging.getLogger("probos.test.bf993.existing")
    existing.setLevel(logging.INFO)
    try:
        with restored_logger_levels():
            existing.setLevel(logging.ERROR)
            made = logging.getLogger(f"probos.test.bf993.made.{uuid.uuid4().hex}")
            made.setLevel(logging.WARNING)
        assert (existing.level, made.level) == (logging.INFO, logging.NOTSET)
    finally:
        existing.setLevel(logging.NOTSET)


def test_the_levels_are_put_back_when_the_block_raises() -> None:
    decomposer = logging.getLogger("probos.cognitive.decomposer")
    before = decomposer.level
    with pytest.raises(RuntimeError), restored_logger_levels():
        decomposer.setLevel(logging.CRITICAL)
        raise RuntimeError("bf993")
    assert decomposer.level == before
```

### 6.6 `PROGRESS.md` (M2)

**P2-1**
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-993 (2026-11-24), #1523, #1815 -- a test that runs `_setup_logging` no longer leaves eleven loggers pinned at WARNING for the rest of its worker.** Test only. `tests/fixtures/logger_levels.py::restored_logger_levels` puts back every named logger's level; `_logger_state` (`tests/test_ad1026_boot_verbosity.py`) and `_handlers` (`tests/test_bf748_file_log_carries_the_date.py`) use it. `tests/test_ad1337_reflect_route.py` sets the decomposer logger's level itself in its two reflect tests. New `tests/test_bf993_logger_level_leak.py` (3 tests). Cause: the reflect test failed in both 3-worker gates of `b428497b` (`bf-981-1815-w3` and `-w3b`, the same test at the same point) because an earlier test of its worker had run `_setup_logging`; reproduced in one process with either polluter file first. The same leak exposes `tests/test_bf875_mcp_inbound_auth.py` and `tests/test_bf876_a2a_inbound_auth.py` (their DEBUG capture through the root logger loses the `probos.federation` records): one case in each fails on the base in one process. Measured with rows kept outside the repository (the contract's section 8): S1 to S4 fail on the base and pass on the candidate. Six of seven mutants are killed by the cases the contract names (M3 by row S4 only, since no committed case observes a fixture's teardown); M4b survives by design, as it makes an absence check real under a pin and changes no outcome. Contract `prompts/bf-993-setup-logging-level-leak.md`.
```

### 6.7 `DECISIONS.md` (M2)

**P2-2** (after the BF-981 part 2 entry)
SEARCH:
```markdown
- *Reversal.* Revert the part-2 commits. Nothing persisted changes.
```
REPLACE:
```markdown
- *Reversal.* Revert the part-2 commits. Nothing persisted changes.

### BF-993 -- Tests that call _setup_logging put back the logger levels it pins (2026-11-24, #1523, #1815)

- *Scope.* Test only: `tests/fixtures/logger_levels.py` (new), `tests/test_bf993_logger_level_leak.py` (new), `tests/test_ad1026_boot_verbosity.py`, `tests/test_bf748_file_log_carries_the_date.py` and `tests/test_ad1337_reflect_route.py`. Contract: `prompts/bf-993-setup-logging-level-leak.md`.
- *Cause (reproduced).* `_setup_logging` pins eleven named loggers at WARNING (`src/probos/__main__.py:187-197`); the two tests that call it restored only the root logger. A later test of the same process that sets only the root level to DEBUG loses the decomposer's DEBUG record (`decomposer.py:501`): the AD-1337 S5 reflect test failed in both 3-worker gates of `b428497b`, at the same point, and fails in one process with either polluter file run first. Which worker ran the polluter in the two gates is not recorded.
- *D1.* Close the leak at the source: one helper puts back every named logger's level (not a list of eleven, so a future pin is covered); both polluters use it.
- *D2.* The observed victim names the logger it reads, so it does not depend on the process's logger state. The two federation tests that the leak also exposes (`test_bf875_mcp_inbound_auth.py`, `test_bf876_a2a_inbound_auth.py`) are covered by D1 and are not edited.
- *Rejected.* A `conftest.py` autouse restore for every test (a registry walk on 54,940 tests, and it would hide future leaks); a change in `_setup_logging` (its pins are right for the CLI).
- *Known limits.* `_setup_logging` also sets the root level, which `_handlers` does not put back (ad1026 does) and which the new test puts back for itself, and it adds AD-754 redaction filters to the handlers on the root logger. Neither is in scope.
- *Reversal.* Revert the BF-993 commits. Nothing persisted changes.
```

## 7. Consumers

| Consumer | What it reads | Status |
|---|---|---|
| the tests of `tests/test_ad1026_boot_verbosity.py` that use `_logger_state` | the fixture's name, scope and teardown order (the helper restores levels first, then the `finally` restores handlers and the root level) | name and scope unchanged |
| `tests/test_bf748_file_log_carries_the_date.py` `rendered` and its five tests | `_handlers()`'s return value, the tuple of the handlers `_setup_logging` attached | unchanged (the `return` runs inside the `with`; the levels are put back, then the `finally` removes the handlers) |
| `tests/test_ad1337_reflect_route.py` | `caplog.records` of the two edited tests; the other eight tests | `caplog.set_level` with a logger name is restored by pytest at the end of the test |
| `tests/test_bf875_mcp_inbound_auth.py:403`, `tests/test_bf876_a2a_inbound_auth.py:447` | `BF-875` and `BF-876` records under `probos.federation.*` through `caplog.at_level` | not edited; row S4 |
| scanners of every `tests/**/*.py`: `tests/test_ad1248_slice_c_one_shape.py:251`, `tests/test_ad1270e2g_crew_models.py:729`, `tests/test_ad1270f_shutdown_grace.py:902` and `:1069` | a literal string set, `src/probos/config.py` read through `Path` or `_text`, and the `fast_teardown` keyword | the new files hold none of them; run in 8.2 |
| `tests/test_ad1346_admission_*census*.py` | `tests/fixtures/ad1346_*` modules; they scan `src` | no `tests/fixtures` scan |
| `tests/test_ad1184_ad_ledger.py` | `gen_ad_ledger.py --check` | M2 regenerates the ledger |
| the AD-1270f duration scheduler (`tests/fixtures/file_durations.json`) | recorded seconds per file | no entry for the new file: it is estimated at the recorded mean, as 352 files are today |

## 8. Gates (the orchestrator runs all of them)

### 8.1 On the oracle tree, before the Builder starts

| # | Check | Expected |
|---|---|---|
| O1 | Every SEARCH in section 6, LF-normalised, counted in its file at its turn; the two new files do not exist | 1 each |
| O2 | `rg -n "restored_logger_levels\|logger_levels\|test_bf993" tests src scripts` on the base | no match |
| O3 | Rows S1 to S4 (8.3) on the base | each fails as the table says, S3's premise holds |
| O4 | Counts of the focused command (8.2) on the base, minus the new file | record them; the candidate adds 3 |

### 8.2 Focused checks on the candidate

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf993_logger_level_leak.py tests/test_ad1026_boot_verbosity.py tests/test_bf748_file_log_carries_the_date.py tests/test_ad1337_reflect_route.py tests/test_bf875_mcp_inbound_auth.py tests/test_bf876_a2a_inbound_auth.py -n 0 -p no:randomly -q
```
Expected: the O4 counts plus 3, all passed. Run it also with the files in reverse order, and with the two polluter files first and the new file last: the same counts, all passed.

Consumers (section 7):
```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py tests/test_standing_orders_layout.py tests/test_ad1248_slice_c_one_shape.py tests/test_ad1270e2g_crew_models.py tests/test_ad1270f_shutdown_grace.py -n 0 -p no:randomly -q
```
Expected: all passed.

### 8.3 Stressor rows (`-n 0 -p no:randomly`, one process per row, files in the order given)

Rows S1, S2 and S4 are plain commands. Row S3 uses a pytest plugin kept outside the repository, `bf993_pin_plugin.py` (the block below equals the file): `pytest_sessionstart` sets `probos.cognitive.decomposer` to WARNING, as `_setup_logging` does, and the plugin logs the level it sees at the setup of every test to `BF993_PIN_LOG`. A row whose log does not show WARNING at the setup of every test is INVALID.

```python
"""Orchestrator tool (outside the repo): BF-993 row S3. A pytest plugin that pins the decomposer logger at WARNING at session start, as probos.__main__._setup_logging does for the life of a process,
and logs the level it sees at the setup of every test, so a row can assert its own premise (every test started under the pin).

Use: PYTHONPATH=<this dir> BF993_PIN_LOG=<path> python -m pytest -p bf993_pin_plugin <files>
"""
import logging
import os
from pathlib import Path

LOGGER = "probos.cognitive.decomposer"


def _log(line: str) -> None:
    with Path(os.environ["BF993_PIN_LOG"]).open("a", encoding="ascii") as handle:
        handle.write(line + "\n")


def pytest_sessionstart(session):
    logging.getLogger(LOGGER).setLevel(logging.WARNING)
    _log(f"session {LOGGER} level={logging.getLogger(LOGGER).level}")


def pytest_runtest_setup(item):
    _log(f"{item.nodeid} level={logging.getLogger(LOGGER).level}")
```

| Row | Files, in order (S3: with the plugin) | Base `b428497b` (measured) | Candidate |
|---|---|---|---|
| S1 | `tests/test_bf748_file_log_carries_the_date.py` `tests/test_ad1337_reflect_route.py` | 1 failed, 14 passed: the reflect test of `:114` fails with `ValueError` at `:133` | all pass |
| S2 | `tests/test_ad1026_boot_verbosity.py` `tests/test_ad1337_reflect_route.py` | 1 failed, 26 passed: the same test, the same error | all pass |
| S3 | `tests/test_ad1337_reflect_route.py` under the plugin | 1 failed, 9 passed: the same test, the same error; the plugin's premise holds (every test started at level 30) | all pass |
| S4 | `tests/test_ad1026_boot_verbosity.py` `tests/test_bf875_mcp_inbound_auth.py` `tests/test_bf876_a2a_inbound_auth.py` | 2 failed, 304 passed: `test_door_a_refusal_logs_no_token` at `:403` and `test_door_refusal_logs_no_token` at `:447` | all pass |

### 8.4 Mutation rows

Run on the candidate, one at a time. A mutant replaces ONE line of ONE file (the line whose stripped text is given; the nth match where a number is given) and keeps its indentation and line ending; the file is restored byte for byte after each row. Each row runs the selectors named, each in its own process; KILLED means a case of a selector failed.

| ID | File | Mutant | Selectors | Expected |
|---|---|---|---|---|
| M1 | `tests/fixtures/logger_levels.py` | the `finally` loop header `for name, logger in list(manager.loggerDict.items()):` becomes `for name, logger in []:` (the whole `finally` body does nothing) | new file, S4 | killed by all three new tests and by S4 |
| M2 | `tests/test_bf748_file_log_carries_the_date.py` | `with restored_logger_levels():` becomes `if True:` (no restore in `_handlers`) | new file, S1, S4 | killed by `test_the_file_log_helper_leaves_the_pinned_loggers_as_it_found_them` |
| M3 | `tests/test_ad1026_boot_verbosity.py` | `with restored_logger_levels():` becomes `if True:` (no restore in `_logger_state`) | new file, S2, S4 | killed by S4 only: no committed case observes fixture teardown, and S2's victim names its own logger |
| M4 | `tests/test_ad1337_reflect_route.py` | the first `caplog.set_level(logging.DEBUG, logger="probos.cognitive.decomposer")` (P1-7) becomes `pass` | S3, S1, S2 | killed by S3 only: S1 and S2 are closed at the source |
| M4b | `tests/test_ad1337_reflect_route.py` | the second (P1-8) becomes `pass` | S3, S1, S2 | SURVIVES by design: the edit makes an absence check real under a pin and changes no outcome |
| M5 | `tests/fixtures/logger_levels.py` | `level = saved.get(name, logging.NOTSET)` becomes `level = saved.get(name, logger.level)` (a logger made inside keeps its level) | new file | killed by `test_a_level_set_inside_is_put_back_and_a_logger_made_inside_is_left_notset` |
| M6 | `tests/fixtures/logger_levels.py` | the `continue` that skips a placeholder becomes `pass` (a placeholder is read as a logger) | new file | killed: a placeholder has no `level` |

### 8.5 The batch gate

BF-993 needs no broad gate of its own. The batch (BF-981 part 2 and this slice) is gated once, on the final head, with `scripts/run_test_gate.py --workers 3` and a receipt: the BF-981 part 2 rule of its section 8.5 stands (two red gates at 16 workers and two at 3 workers are on record, #1815 comments 7136253260 and 7139799870, #1523 comments 7136234751 and 7138100798). Expected: 54,759 passed, 184 skipped, 54,943 nodes (the base gate's 54,756 passed and 184 skipped, plus the 3 new tests). A red test outside this family and outside the files of this contract: the F-240 convention (record it on #1523, re-gate the unchanged commit once). A red test in a file this contract or BF-981 part 2 changes, or the reflect test again: stop for Architect triage.

## 9. Diff Reviewer: properties to verify

The change claims to end the logger-level leak that made the AD-1337 S5 reflect test fail in two canonical gates. The consumer that must accept it is the canonical gate, which runs all 54,943 tests at 3 workers. Report each finding with its severity, its reach (ordinary or injected-only) and whether the repair introduced it.

1. With the candidate in place, no test that calls `_setup_logging` leaves a named logger's level changed (the callers in `tests/` are `tests/test_ad1026_boot_verbosity.py` and `tests/test_bf748_file_log_carries_the_date.py`, section 10).
2. The helper puts levels back when the block raises, and leaves a logger created inside it at NOTSET.
3. No fixture name, test name or imported helper changes (`_logger_state`, `_handlers`, `rendered`, and the reflect file's imports).
4. P1-7 and P1-8 keep the root `caplog.set_level` call, so the escalation and masking records are still captured.
5. ASCII and LF throughout; no production file, no pytest or CI configuration changes.
6. No census or scanner under `tests/` rejects the new fixture module or the new test (section 7).
7. The new test leaves no state behind: it puts back the root level, the pinned levels and closes the file handler `_setup_logging` opened.
8. Rows S1 to S4 discriminate: they fail on the base for the reason the table gives, and pass on the candidate with the polluter's cases present (the per-file counts show them).

## 10. Verified Against Codebase (2026-11-24, tree `b428497b`)

- `git rev-parse HEAD` `b428497bc4d573d56786a0d6b0c4cc9d45ec359d`, tree `704692693cd8`; `git status` clean; `origin/main` `542a2a68`; `git rev-list --count HEAD..origin/main` is 0.
- `src/probos/__main__.py`: `_setup_logging` at `:132`; the root level at `:153`; the eleven pins at `:187-197` in the order `asyncio`, `aiosqlite`, `httpx`, `httpcore`, `probos.substrate.agent`, `probos.federation`, `probos.cognitive.decomposer`, `probos.mesh.intent`, `probos.mesh.routing`, `probos.substrate.spawner`, `probos.substrate.pool`; AD-754 redaction at `:199-206`; its one call in `src` at `:593`, inside `_boot_runtime`, which `_boot_and_run` (`:687`) and `_serve` (`:818`) call. `_serve` calls it after the pidfile, shutdown-integrity and episodic-health refusals.
- `src/probos/cognitive/decomposer.py:30` `logger = logging.getLogger(__name__)`; `:501` the `Reflect prompt` DEBUG record.
- `tests/test_ad1337_reflect_route.py`: the unpack at `:133`, the absence check at `:189`, the anchors of P1-7 at `:114-118` and P1-8 at `:172-176`. `tests/test_bf748_file_log_carries_the_date.py`: imports `:16-19`, `_handlers` `:25-40`, `rendered` `:53-63`. `tests/test_ad1026_boot_verbosity.py`: docstring `:10-13`, imports `:22-24`, `_logger_state` `:29-52`. `tests/fixtures/__init__.py` exists and `tests/fixtures/logger_levels.py` does not; `PROBOS_DATA_DIR` is set by `tests/conftest.py:17`, and `_platform_data_dir()` honors it (`runtime.py:246-248`), so the file log of `_setup_logging` lands in a temporary directory.
- Counts of the focused files on the base (row S4 and the S rows): `test_bf748...` 5, `test_ad1026...` 17, `test_ad1337_reflect_route.py` 10, `test_bf875...` 179, `test_bf876...` 110.
- BF number: highest BF-991 over three sources (the roadmap's Bug Tracker tops out at BF-927, and git subjects at BF-961). Run with `bf_ceiling3.py` on 2026-11-24 18:07Z: `git log --all --format=%s` subjects (558 distinct numbers) highest BF-961; GitHub issue titles in all states (1,544 issues read, highest #1840; 451 numbers) highest BF-991; `prompts/bf-*.md` names (85 numbers) highest BF-991; `docs/development/roadmap.md` (38 numbers) highest BF-927. BF-992 is in none of them (it is allocated to #1324 in the orchestrator's notes); BF-993 is in none. The Architect's three searches agree (`prompts/bf-99*.md` holds `bf-990` and `bf-991`; `gh search issues "BF-992 OR BF-993 OR BF-994"` returned nothing; `git log --all --grep=BF-99` is empty). AD ceiling AD-1361, not used.
- Duplicate search (`dup_search.py` over 1,544 issues, 2026-11-24): `_setup_logging`, `restored_logger_levels`, `logger_levels`, `test_ad1026_boot_verbosity`, `test_bf748_file_log`, `pins eleven`, `test_bf875_mcp_inbound_auth`, `test_bf876_a2a_inbound_auth` find no issue about this leak (the hits are #970 AD-1026 and #1820, whose AD-1337 items name the reflect test file for other reasons). `test_ad1337_reflect_route` appears in open #1820 only.

### Absence Verified (2026-11-24)

Run on tree `b428497b`:
- `grep -rn "_setup_logging" tests src`: `src/probos/__main__.py:128`, `:132`, `:593`; `tests/test_ad1026_boot_verbosity.py` (calls at `:134`, `:143`, `:152`, `:162`, `:206`, `:216`) and `tests/test_bf748_file_log_carries_the_date.py:27`, `:34`. No other file.
- `grep -rn "_boot_runtime" tests`: `test_ad1341_s1_reset_and_erase.py:152` (a stub inside a child script), `test_bf984_rebuild_binding.py:36`, `:76` (a census of constructions). `_boot_and_run`: `test_ad1135_setup_cli.py:1561` (monkeypatched), `test_bf207_shutdown_episodic_integrity.py:301` (`inspect.getsource`). `_serve(`: `test_ad1341_s1_reset_and_erase.py:157` (the child script with the stub), `:886` and `:970` (in process; the lock and pid refusals end in `SystemExit(2)` before `_boot_runtime`). `from probos.__main__ import main`: `test_dotenv.py:15`, `:35` (`--help`). So no test reaches `_setup_logging` through `_boot_runtime`.
- `grep -rn "\.setLevel(" src`: only `__main__.py` (`:153`, `:164`, `:180`, `:187-197`). `grep -rn "\.setLevel(" tests`: `test_ad1026_boot_verbosity.py:52`, `test_ad1270f_shutdown_grace.py:552`/`:559`, `test_bf904a_failed_build_restore.py:1466`/`:1494`, `test_bf927_boot_claims.py:551`/`:560` (each puts the level back) and `test_pii_redaction.py:78` (a private logger, `test.ad754.redaction`).
- `basicConfig(`, `dictConfig(` and `logging.disable(` in `tests`: `tests/fixtures/ad1174_progress_bridge.py:311`, `consulted_evidence_bridge.py:531`, `federation_cluster_node.py:235` (each under `if __name__ == "__main__":`, a child process) and `test_bf884_sidecar_bind_failure.py:43` (inside its `_CHILD` script string). None runs in the test process.
- The four scanners of section 7 (`rglob("*.py")` over `tests`) and the AD-1346 censuses read nothing the new files hold.

## 11. What this does NOT change, and recorded limits

- No production code, no `_setup_logging` pin, no pytest or CI configuration, no `conftest.py`.
- The root level: `_setup_logging` sets it (`:153`), `_handlers` has never put it back (the module-scoped `rendered` fixture leaves it at INFO for the rest of its worker), and the helper restores named loggers only. The new test puts back the root level it changes; `_handlers` stays as it is. No failure is attributed to it.
- AD-754 redaction: `_setup_logging` adds redaction filters to the handlers on the root logger (`:199-206`). Not in scope.
- About 50 test files use `caplog.set_level` or `caplog.at_level` at DEBUG or INFO without naming a logger (the Architect's count, not enumerated). With the two sources closed they are no longer exposed to these pins. A third source (a test that pins a logger and does not put it back) is not found by the enumeration of section 10.
- Which worker ran which polluter in the two failed gates is not recorded; the cause rests on the reproduction in one process (rows S1, S2) and on the same test failing at the same point twice.
- M4b survives by design and M3 is killed by row S4 only, as the table of 8.4 says.

## 12. Issue texts

**#1523 flake record update** (post after the merge, with the measured rows of section 15):

```
**Update (2026-11-24): second red, now a blocker, repaired as BF-993 inside the BF-981 part 2 batch (#1815).** The unchanged re-gate `bf-981-1815-w3b` failed the same test at the same point (`1 failed, 54755 passed, 184 skipped`; no receipt). Repair (test only): `tests/fixtures/logger_levels.py::restored_logger_levels` puts back every named logger's level; `_logger_state` (test_ad1026) and `_handlers` (test_bf748) use it; the reflect tests name `probos.cognitive.decomposer` in `caplog.set_level`. The same leak exposed `test_bf875_mcp_inbound_auth.py:403` and `test_bf876_a2a_inbound_auth.py:447` (their capture through the root logger loses the `probos.federation` records); they are covered by the source repair. Evidence: stressor rows S1-S4 and the mutation rows in `prompts/bf-993-setup-logging-level-leak.md`; the batch's single 3-worker gate covers it.
```

## 13. Prior art and blind spots

- Prior art: BF-981 part 1 and part 2 (the same family of gate-load test premises), BF-913 and BF-951 (a test fixed only where it had failed), AD-1270f (the duration scheduler that makes the plan near-deterministic per tree, so a polluter and a victim on one worker repeat), the F-240 convention on #1523 (an unrelated first red is recorded and the unchanged commit re-gated once; a second red on the same test is a blocker fixed in the batch as a numbered test-only change), `caplog`'s own restore of the levels it sets.
- **Where the orchestrator's text differs from the consult 91af63b3:**
  1. P1-9, the first test: it saves the root level before the `with` and puts it back in a `finally` (the consult's text left the root at INFO after `_handlers()`). The helper itself stays as the consult wrote it (named loggers only), so no other test changes behaviour.
  2. P2-1 and P2-2: the measured rows replace the expectations, and the consult's sentence that the duration plan put the polluter first on that worker is replaced by the statement that the worker assignment is not recorded.
  3. Rows M4b and M6 are added (the consult listed M1 to M5); the `--rows` and the focused command are the consult's.
  4. The reverse-order and polluters-first runs of 8.2 are added.
- Blind spots: the third source above; the reflect test's `:217` and `:234` neighbours are shown to pass under the pin by S3's nine passing cases, not by a trace of every logger they read; the gate's worker assignment.

## 14. Acceptance criteria

1. Rows S1 to S4 fail on the base for the reasons of 8.3 and pass on the candidate, with the polluter's cases present in the counts and S3's premise holding.
2. Rows M1 to M6 give the verdicts of 8.4 (M4b survives by design).
3. The focused checks of 8.2 pass in the three orders, and the consumers pass.
4. `git diff --check` is clean, every new line is ASCII, no file outside the list of section 4 changes, and the Builder's blobs equal the oracle's.
5. The Diff Reviewer approves the slice (the properties of section 9).
6. The batch's canonical gate at 3 workers on the final head is green with a receipt: 54,759 passed, 184 skipped, 54,943 nodes.

## 15. Results on the oracle trees (the orchestrator, 2026-11-24)

The base oracle is a clean detached tree at `b428497b`; the candidate is that tree with the pairs of section 6 applied by `contract_tools.py` (every SEARCH occurred once at its turn; `ws_ambiguity.py`: 0 hazards; `git diff --check` clean). The rows ran with `bf993_rows.py` (outside the repository): one pytest process per selector, `-n 0 -p no:randomly`, `HOME` and `USERPROFILE` redirected to an empty directory (empty afterwards), the cases read from the JUnit file.

### 15.1 Stressor rows S1 to S4 (section 8.3)

| Row | Base `b428497b` | Candidate |
|---|---|---|
| S1 | bf748 5 passed; reflect 9 passed, 1 failed (`test_every_form_in_a_node_result_is_masked_before_the_model_and_the_log`, `ValueError` at `:133`) | bf748 5, reflect 10: 15 passed |
| S2 | ad1026 17 passed; reflect 9 passed, 1 failed (the same test, the same error) | ad1026 17, reflect 10: 27 passed |
| S3 | reflect 9 passed, 1 failed (the same test, the same error); premise holds: every test started at level 30 | reflect 10: 10 passed; premise holds |
| S4 | ad1026 17 passed; bf875 178 passed, 1 failed (`test_door_a_refusal_logs_no_token`, `:403`); bf876 109 passed, 1 failed (`test_door_refusal_logs_no_token`, `:447`) | ad1026 17, bf875 179, bf876 110: 306 passed |

### 15.2 Focused checks (section 8.2)

- The focused command, forward: 324 passed in 20.74 s (5 + 17 + 10 + 179 + 110 = 321 on the base, plus the 3 new). Reverse order: 324 passed. The two polluter files first and the new file last: 324 passed.
- Consumers (the ledger, standing-orders layout and the three scanners): 553 passed, 1 warning (an `importlib_metadata` deprecation, unrelated), 94.83 s.
- `gen_ad_ledger.py` (no `--online`) rewrote `docs/development/ad-ledger-snapshot.json` (`captured_at`, `head`, `subject_count`) and `docs/development/open-ads-report.md` (the BF ceiling is BF-993 and the next BF-994; BF-993 is counted as shipped, and BF-992, allocated to #1324 and in no authority yet, appears among the numbers below the ceiling that no authority mentions).

### 15.3 Mutation rows (section 8.4), one at a time, each file restored byte for byte

| ID | Verdict | Killed by (selector: result) |
|---|---|---|
| M1 | KILLED | new file: 3 failed (the pinned levels stay at 30); S4: 2 failed (`:403`, `:447`) |
| M2 | KILLED | new file: 1 failed (`test_the_file_log_helper_leaves_the_pinned_loggers_as_it_found_them`); S1 and S4 pass |
| M3 | KILLED | S4: 2 failed (`:403`, `:447`); the new file and S2 pass, as the table predicted |
| M4 | KILLED | S3: 1 failed (`ValueError` at the reflect test's unpack); S1 and S2 pass |
| M4b | SURVIVED | every selector passes: by design |
| M5 | KILLED | new file: 1 failed (`assert (20, 30) == (20, 0)`, the logger made inside kept WARNING) |
| M6 | KILLED | new file: 3 failed (`AttributeError: 'PlaceHolder' object has no attribute 'level'`) |
