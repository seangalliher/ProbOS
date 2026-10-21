# BF-913: the child-start-sensitive tests get windows that hold under load

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21 (Amendment A1, section 15: prose only)

**Status:** build-ready. **Part of #1523** (F-194 and F-195, the "child-start budget family"; #1523 stays open). **Tier LOW** (test-only): one cross-family review round, the mutation rows in section 9, one receipted broad gate (because `tests/` changes). **Base:** `origin/main` `b72194ab`. **Dependencies:** none. **Tests:** 0 new, 7 changed (the list in section 6 is the one statement of it). **Source:** option (a') of the Architect's consult of 2026-10-21 (18:12Z), re-verified on this tree; section 2 says where this contract departs from it, and why.

**Not in this contract:** product code; the gate wrapper (`scripts/run_test_gate.py`, `scripts/_gate_pytest_plugin.py`); CI; F-193 (`knowledge/store.py`, its own MEDIUM slice).

**Line endings:** the working copies of all four edited files are CRLF (`git ls-files --eol`: `i/lf w/crlf`). The SEARCH blocks below are written with LF; match and write with the file's own line endings.

---

## 1. Problem

Five of twelve canonical gate runs kept in the 2026-10-21 session were red, every failure in this family, each green on an unchanged re-gate (`register-flake-family.md`, the table on #1523). The product code under test is correct; the recorded failures (#1523 F-187, F-194, F-195, F-197; each failing assertion is in the table below) show windows too short for a child's start under the gate's parallel load (16 workers in batch A r1 to r3, 12 in r5, 8 in the BF-911 first gate). On Windows the shell and red-team agents start every command as `powershell -NoProfile -Command <command>` (`src/probos/agents/shell_command.py:292`, `src/probos/agents/red_team.py:474`), so their heartbeat tests wait for PowerShell, a Python root, a Python grandchild and its beats. The SWE `run_command` tool starts its command through `asyncio.create_subprocess_shell` (`src/probos/cognitive/swe_harness/tools.py:1316`), and AD-1246 M1's child is started by `SubprocessSandbox` as `python -I -B` directly (`src/probos/execution/isolation.py:1007-1038`): neither waits for PowerShell.

| Test (`tests/test_bf893_process_tree.py` unless named) | The window on this tree | What it must contain |
|---|---|---|
| `test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop` (`:768`) | deadline `DEFAULT_TIMEOUT = 2.0` (`:779`), executor held `asyncio.sleep(1.0)` (`:788`): 1.0 s from release to the deadline | the whole start chain and two beats, before `_heartbeat_is_running` (`:791`) sees `call.done()` (`:356`, `:358`). Failed in batch A r1, r2, r3 and the BF-911 first gate ("premise: the grandchild never started", `Command timed out after 2.0s`) |
| `_beats_until_ended` (`:334-349`), the control of five tests | a fixed `asyncio.sleep(0.5)` (`:343`) from `.started` to the rise check (`:344`) | the grandchild's cold Python start and its first two beats. Failed at `:344` (`0 > 0`) in the BF-911 first gate (`test_shell_cancel_ends_tree`) and in the batch A contract dry run (the shell `_started_late_` test's control, #1523 F-187) |
| the two `_started_late_` tests (`:726`, `:839`) | deadline 3.0 s (`:750`, `:856`), held 1.0 s (`:756`, `:862`): 2.0 s | the start chain and two beats before the deadline, for `_assert_silent_after_the_call`'s premises (`:364`, `:366`). No failure of this window recorded; widening it is preventive (the late-worker row's shape). The shell test's control did fail once (F-187): the control row above |
| `tests/test_ad1246_long_run_promotion.py::test_m1_long_run_promotes_keeps_running_and_reports_once` (`:270`) | promotion at 0.6 s (`:278`), premise `1 <= beats_at_ack < 30` (`:293`) | the scripted turn, the sandbox start, a Python start and the first beat. Failed in batch A r1 and r5, both at `:293` with `beats_at_ack == 0` (#1523 F-194, F-197): the child had written no beat at the 0.6 s promotion. The child is started by `SubprocessSandbox` (`src/probos/execution/isolation.py:1007-1038`), not PowerShell |

A second defect, found while deriving the mutation rows: **the control's stop check does not discriminate the stop file.** `_beats_until_ended` asks the grandchild to stop (`:345`), awaits the call (`:346`) and checks the count is still (`:347-349`). A beater that ignores the stop file also passes: the call then returns at its own deadline, after `tree.kill()` (`shell_command.py:320`, `red_team.py:493`), and the count is just as still. So the consult's validation row "remove the stop file from the control; the control check must fail" has no assertion that fails on this tree.

## 2. Solution overview

Fix the premises, not the guarantees (consult option (a')): each window that waits for a process to start gets room for the start chain, and each assertion that tells a correct behaviour from a defect keeps a stated gap. Where this contract departs from the consult:

1. **The control's rise window is 1.0 s, not 2 s.** The control exists so that "the count did not change for 1.0 s" in `_assert_silent_after_the_call` (`:367`) means "nothing is beating". A control that allows a live beater 2 s to advance would no longer show that a live beater advances within the 1.0 s the check waits. Both now read one constant, `_SILENT_SECONDS = 1.0`. The late first beat (the count read `0 > 0` at `:344` in both recorded control failures; a cold start of the grandchild is the inferred reason) is handled by polling for the first beat, as the consult said.
2. **The control requires the call's in-time result after the stop request** (a predicate passed by each caller), so a beater that ignores the stop file fails the control (row T4). This is an addition to the consult; the consult assumed the existing check did it.
3. **The stress harness runs seven tests, not six**: the helper change reaches five tests (section 5), and with the late-worker test and M1 that is seven. Leaving one out would leave a changed window unexercised.

## 3. Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | Test files only: fix each start window and keep each discriminating gap (consult (a')) | (b) a marker plus a serial lane in the gate wrapper: a HIGH-tier shared-contract change that hides thin budgets (fallback only). (c) a spawner without PowerShell: `_run_sync` wraps every command in PowerShell (`shell_command.py:292`), so it stops testing the production chain. (d) fewer workers: every gate pays and the cause stays. (e) bounded retry of marked tests: a real timing regression (a budget restarted at pickup, a late tree kill) also fails only sometimes, and a retry passes it. `xdist_group`: no effect, `--dist=loadfile` (`pyproject.toml:196`) already keeps each file on one worker |
| D2 | Late-worker test: deadline 4.0 s, grace 6.0 s (kept), hold 1.0 s (kept), assert `elapsed < 4.7` | A 2.0 s hold with a 5.0 s deadline and a 6.0 s bound (1.0 s on both sides) costs 1 s per run; the 0.7 s margin on the correct side is the base's (2.7 against 2.0), where no failure of this assertion is recorded |
| D3 | `_started_late_` tests: deadline 4.0 s, grace 0.5 s (kept), hold 1.0 s (kept) | Raising the grace: the hold (1.0 s) must stay longer than the grace, or the red-team test no longer tells the worker's verdict from the backstop's (row T2) |
| D4 | `_beats_until_ended`: `.started`, the first beat and the rise share one 20 s budget; the rise must come within `_SILENT_SECONDS` (1.0 s) of the first beat seen | The consult's 2 s rise window (section 2, item 1); a fixed sleep (the defect) |
| D5 | `_beats_until_ended` takes `in_time: Callable[[Any], bool]` and asserts it on the call's result after the stop request | Returning the result for each caller to check (five assertions instead of one); a timing bound on the stop (depends on each caller's deadline) |
| D6 | One constant `_SILENT_SECONDS = 1.0`, read by the silence check and the control | Two literals that can drift apart |
| D7 | M1: promotion at 2.0 s over `_beats_code(beat_file, 50)`; `1 <= beats_at_ack < 50`; the totals read 50 | A longer child than 50 beats: `_beats_code` asserts `beats <= 50` (`test_ad1246_long_run_promotion.py:229`), and 50 already leaves at least 2.9 s after promotion |
| D8 | `_heartbeat_is_running` (`:352-359`) unchanged | It already polls 20 s for `.started` and 20 s for two beats; its callers' windows come from their call deadlines (section 5) |
| D9 | The stress harness is not committed (`logs/` is ignored, `.gitignore:121`) | A committed stress test: it runs 30 times under load, which no gate should pay for |

## 4. Milestones (about 30 Builder tool calls)

| M | Work | Focused check (`-n 0`, the orchestrator's worktree environment: `PYTHONPATH=<tree>/src`, as `scripts/run_test_gate.py:817-818` sets it) |
|---|---|---|
| M1 (about 14 calls) | Section 7.1, blocks 1-10, in order | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf893_process_tree.py -n 0 -q` |
| M2 (about 6 calls) | Section 7.2, blocks 11-14 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1246_long_run_promotion.py -n 0 -q` |
| M3 (about 7 calls) | Section 8: `PROGRESS.md`, `DECISIONS.md`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` | `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -n 0 -q` |
| M4 (about 3 calls) | Section audit against this contract; stage by explicit path: the two test files, `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` (never `git add -A`) | `git diff --cached --stat` |

Then the orchestrator: the scratch-tree dry run of the whole contract, the harness on the base and on the fix (section 10), the mutation rows (section 9), one cross-family review round, the commit, one receipted broad gate, the PR.

## 5. Consumers of every helper and constant this contract changes or that the request named

Greps run on `b72194ab` (output in section 11).

| Name | Changed? | Consumers (`tests/test_bf893_process_tree.py` unless named) | With the new numbers |
|---|---|---|---|
| `_beats_until_ended` | yes (D4, D5) | `:744` shell `_started_late_` (control `DEFAULT_TIMEOUT = 10.0`, `:740`); `:852` red `_started_late_` (`_RERUN_TIMEOUT_S` 10.0, `:848`); `:891` `test_shell_cancel_ends_tree` (`DEFAULT_TIMEOUT = 20.0`, `:883`); `:927` `test_redteam_outer_timeout_ends_rerun` (10.0, `:923`); `:1122` `test_swe_run_command_cancel_ends_tree` (tool `"timeout": 20`, `:1120`). No other file | Each keeps its control deadline. Each control now waits up to 20 s in all for start, first beat and rise (was 20 s for `.started` plus a fixed 0.5 s), needs a rise within 1.0 s of the first beat (was within 0.5 s of `.started`), and must return its in-time result after the stop request (new). An in-time control on an idle host ends when the stop file is honoured, about 0.1 s after the stop request plus process exit; the deadline is reached only by a failing control |
| `_SILENT_SECONDS` | new | `_beats_until_ended` (rise window); `_assert_silent_after_the_call` (`:367`), whose callers are `:761`, `:796`, `:868`, `:901`, `:939`, `:1132` | The silence wait stays 1.0 s for all six callers (value unchanged) |
| `_heartbeat_is_running` | no | `:791` late-worker, `:897` shell cancel, `:935` red outer, `:1128` swe cancel | Unchanged: 20 s for `.started`, then up to 20 s for two beats, ending early on `call.done()`. For the late-worker test the call's end is now its 4.0 s deadline (was 2.0 s): 3.0 s after the release for the start chain and two beats (was 1.0 s) |
| `_appears_async` | no | `:341`, `:354`, `:722`, `:835`, `:984` | Unchanged |
| `_beats_code` (`test_ad1246_long_run_promotion.py:227`) | no | `:282` M1 (30 → 50), `:480` M2 (50), `:618` M3 (20), `:736` M4 (50). `tests/test_ad1246_long_run_units.py:53` and `tests/test_issue1417_run_python_child_ownership.py` hold their own copies | Only M1's argument changes; the helper's `assert beats <= 50` admits 50 |
| `_spawner_command`, `_BEAT_LIMIT_SECONDS` | no | the beater tests (`:742`, `:754`, `:786`, `:850`, `:860`, `:889`, `:895`, `:925`, `:933`, `:1120`, `:1125`) and the spawner tests | Unchanged: the grandchild beats at most 60 s; every test ends it first |
| `DEFAULT_TIMEOUT` (set on a fresh `ShellCommandAgent`) | `:750` 3.0 → 4.0; `:779` 2.0 → 4.0 | others unchanged: `:422` 20.0, `:609` 60.0, `:616` 4.0, `:701` 10.0, `:711` 1.5, `:740` 10.0, `:883` 20.0, `:1013` 0.5. No other test file sets it | Instance attributes on per-test agents: no test reads another's value |
| `WORKER_TEARDOWN_GRACE` | no | `:751` 0.5, `:780` 6.0, `:1014` 0.5 | Unchanged values; their gaps are restated in section 6 |
| `_RERUN_TIMEOUT_S` (monkeypatched) | `:856` 3.0 → 4.0 | others unchanged: `:430` 20.0, `:814` 10.0, `:823` 1.5, `:848` 10.0, `:923` 10.0, `:929` 5.0, `:1030` 0.5 | `monkeypatch.setattr` restores it after each test |
| `_RERUN_TEARDOWN_GRACE_S` | no | `:857` 0.5, `:1031` 0.5 | Unchanged |
| `promote_to_task_after_seconds` in `test_ad1246_long_run_promotion.py` | `:278` 0.6 → 2.0 | `:351` `_SHORT_RUN_PROMOTE_AFTER` (5.0), `:399` `promote_after`, `:475`, `:528`, `:609` (0.6) unchanged. Other files set it for their own tests (section 11) | Only M1 changes |

## 6. Each window's derivation

Times are from the test's own clock (`time.monotonic()`); "at least" bounds come from sleeps and deadlines, which load can lengthen but not shorten.

**The seven changed tests** (the harness runs exactly these): the shell `_started_late_` test (`:726`), the late-worker test (`:768`), the red `_started_late_` test (`:839`), `test_shell_cancel_ends_tree` (`:875`), `test_redteam_outer_timeout_ends_rerun` (`:909`), `test_swe_run_command_cancel_ends_tree` (`:1112`), and AD-1246 M1 (`:270`).

| Window | Correct behaviour | Mutant | Gap the assertion separates |
|---|---|---|---|
| Late-worker start room | release at ≥ 1.0 s; the start chain and two beats must finish before the 4.0 s deadline: 3.0 s (was 1.0 s; idle chain 0.38-0.66 s in the consult's probes, which I did not re-run) | — | premise only |
| Late-worker report, `elapsed < 4.7` | the worker's communicate budget ends at the shared deadline, 4.0 s; tree kill and return follow: 0.7 s of room (the base's margin, 2.7 against 2.0) | row T1, a budget restarted at pickup: communicate gets 4.0 s from pickup, and pickup is ≥ 1.0 s after `started`, so the report is at ≥ 5.0 s | 4.7 against ≥ 5.0: 0.3 s, a lower bound the mutant cannot undercut |
| Late-worker grace 6.0 s | backstop at 4.0 + 6.0 = 10.0 s, after both the correct report and the mutant's | a worker that reported at the backstop | 10.0 against 4.7 |
| `_started_late_` start room | 4.0 − 1.0 = 3.0 s for the start and two beats before the deadline (was 2.0 s) | — | premise only (`:364`, `:366`) |
| Red `_started_late_`, verdict string | the worker returns `None` at 4.0 s, before the backstop at 4.0 + 0.5 = 4.5 s: "Verification command timed out" (`red_team.py:339`) | row T2: the worker would return at ≥ 1.0 + 4.0 = 5.0 s; the backstop fires at 4.5 s and its `TimeoutError` becomes "Verification error: " (`red_team.py:395-402`) | hold 1.0 s > grace 0.5 s: 4.5 against ≥ 5.0. Correct side: 0.5 s of teardown room, the base's (3.0 against 3.5) |
| Shell `_started_late_` | the same timing; the slot ends the tree at the backstop, so this test does not tell row T1 apart (the late-worker test does, as its docstring says) | — | — |
| Control rise, `_SILENT_SECONDS` = 1.0 s | after the first beat, one beat per 0.1 s: ten beat periods | a beater that beats once and stops | the rise window equals the silence window it supports (D4) |
| Control first beat, 20 s shared | cold start of the root and the grandchild | — | premise only; ends early when the call ends |
| Control in-time result | the stop file ends the grandchild within one beat period; the root, the shell and the call return before the control's deadline (10 s or 20 s from the call's start) | row T4, the stop file ignored: the call ends only by its deadline, with the timeout result (`{"success": False, ...}`, `verified is False`, or a `ToolResult` with `error`) | the result type, not a time |
| M1 lower bound `1 <= beats_at_ack` | promotion at 2.0 s after the turn's wait starts (`turn_promotion.py:2442-2443`); the scripted turn, the sandbox and a Python start must write one beat before it (was 0.6 s) | row P1, promotion at 0 s: the ack follows within the work-item insert, before the child's first beat (expected; section 9) | 2.0 s against about 0 s |
| M1 upper bound `beats_at_ack < 50` | 50 beats take at least 4.9 s of sleeps after the child starts; at the ack, about 2 s in, the child is running | a promotion after the run finished: the fast path returns the run's text instead (`turn_promotion.py:2445-2448`) and no work item exists (row P2) | at least 2.9 s between the promotion and the child's last beat; check (b) needs 0.5 s of it |

**Platforms.** None of the seven tests is skipped on either platform (section 11: their only markers are `@pytest.mark.timeout(90)`; M1 has none). `_ON_WINDOWS` (`:66`) selects only the shell: `_spawn_shell` (`:190`) and the `powershell=_ON_WINDOWS` argument of `_spawner_command` (`:165-168`); the swe test passes `powershell=False` on both. So the added waits apply on `ubuntu-latest` too.

**Runtime of each changed test** (correct path; the deterministic part of the change):

| Test | Change in wall time |
|---|---|
| late-worker | +2.0 s (the call lasts to its 4.0 s deadline, was 2.0 s) |
| shell and red `_started_late_` | +1.0 s (deadline 4.0 s, was 3.0 s), less up to 0.4 s in the control |
| shell cancel, red outer, swe cancel | up to −0.4 s: the control's fixed 0.5 s sleep becomes a poll that returns at the next beat |
| M1 | +2.0 s (50 beats, was 30) |

**Poll caps against `@pytest.mark.timeout(90)`** (the sum of every poll's cap, ignoring that most end early; M1 is under the global `timeout = 180`, `pyproject.toml:190`):

| Test | Sum of caps after (base) | Bound when each poll stops at its call's end |
|---|---|---|
| control helper alone | 20 shared + 20 `wait_for` + 0.5 = 40.5 s (base 20 + 0.5 + 20 + 0.5 = 41.0) | the control call ends by its own deadline plus grace (≤ 25 s from its start); the helper is about that long at most |
| shell cancel | 40.5 + 40 + 1.0 + 3.0 + 2 × 2.0 = 88.5 s (89.0) | about 25.5 + 25 + 8 = 58.5 s |
| red outer | 40.5 + 40 + 1.0 + 1.0 + 3.0 + 4.0 = 89.5 s (90.0) | about 22 + 20 + 9 = 51 s |
| swe cancel | 40.5 + 40 + 1.0 + 4.0 = 85.5 s (86.0) | lower than shell cancel |
| `_started_late_` (each) | 40.5 + 1.0 + 15 + 1.0 + 4.0 = 61.5 s (62.0) | about 22.5 + 1 + 4.5 + 5 = 33 s |
| late-worker | 1.0 + 40 + 15 + 1.0 + 2.0 = 59 s (59) | about 24 s |
| M1 (no marker; global `timeout = 180`) | 10 `wait_for` (`:287`) + 0.5 (`:298`) + 15 drain (`:117`) + 5.0 `wait_settled` (`:262`) = 30.5 s (30.5; no cap changes) | the child's sleeps are 5.0 s (were 3.0 s), inside the 15 s drain |

(`_stop_heartbeat` is at most 8 × 0.25 = 2.0 s per call, `:241-243`; `is_free(3.0)`, `:902`, `:940`.) Each sum is lower than the base's or equal; the largest, 89.5 s, is under the 90 s timeout, before process teardown overheads, which the second column shows are not reached together.

## 7. The contract

### 7.1 `tests/test_bf893_process_tree.py`

**Block 1: import `Callable`**

SEARCH:
```python
import time
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
```
REPLACE:
```python
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
```

**Block 2: one statement of the silence window**

SEARCH:
```python
#: How long the heartbeat grandchild may beat (one beat per 0.1 s). Nothing waits for that: a test ends it first.
_BEAT_LIMIT_SECONDS = 60

#: The spawner starts a grandchild that writes ``marker`` after ``seconds``, records the grandchild's
```
REPLACE:
```python
#: How long the heartbeat grandchild may beat (one beat per 0.1 s). Nothing waits for that: a test ends it first.
_BEAT_LIMIT_SECONDS = 60

#: How long a check waits before it calls a heartbeat silent; the controls require a live beater to advance within it.
_SILENT_SECONDS = 1.0

#: The spawner starts a grandchild that writes ``marker`` after ``seconds``, records the grandchild's
```

**Block 3: the control waits for the first beat and requires the in-time result**

SEARCH:
```python
async def _beats_until_ended(marker: Path, call: asyncio.Task[Any]) -> None:
    """Control for the heartbeat checks: a command nothing ends keeps beating, until the test asks it to stop.

    *call* runs a heartbeat command under a generous deadline and is never cancelled. Wait for its grandchild to
    start, watch the count advance (so "unchanged" in the real check can be told from "still beating"), then ask
    the grandchild to stop (the stop file), let the call finish and see the count stop.
    """
    assert await _appears_async(_started(marker), 20), "control: the grandchild never started"
    first = _beats(marker)
    await asyncio.sleep(0.5)
    assert _beats(marker) > first, "control: a command nothing ended did not keep beating"
    _request_stop(marker)
    await asyncio.wait_for(call, timeout=20)
    stopped = _beats(marker)
    await asyncio.sleep(0.5)
    assert _beats(marker) == stopped, "control: the stop request did not end the heartbeat"
```
REPLACE:
```python
async def _beats_until_ended(marker: Path, call: asyncio.Task[Any], in_time: Callable[[Any], bool]) -> None:
    """Control for the heartbeat checks: a command nothing ends keeps beating, until the test asks it to stop.

    *call* runs a heartbeat command under a generous deadline and is never cancelled. Wait, 20 s in all, for its
    grandchild to start and write its first beat (BF-913: a cold start under load can take longer than the fixed
    0.5 s this waited before), then for the count to advance within ``_SILENT_SECONDS``, the window the real check
    gives a live beater (so "unchanged" there can be told from "still beating"). Then ask the grandchild to stop
    (the stop file): the call must return the result *in_time* accepts, which a command ended by its own deadline
    does not, and the count must stop.
    """
    deadline = time.monotonic() + 20
    assert await _appears_async(_started(marker), 20), "control: the grandchild never started"
    while _beats(marker) < 1 and not call.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    first = _beats(marker)
    assert first >= 1, "control: the grandchild never wrote its first beat"
    rise_by = min(time.monotonic() + _SILENT_SECONDS, deadline)
    while _beats(marker) <= first and time.monotonic() < rise_by:
        await asyncio.sleep(0.05)
    assert _beats(marker) > first, "control: a command nothing ended did not keep beating"
    _request_stop(marker)
    result = await asyncio.wait_for(call, timeout=20)
    assert in_time(result), "control: after the stop request the call did not return its in-time result"
    stopped = _beats(marker)
    await asyncio.sleep(0.5)
    assert _beats(marker) == stopped, "control: the stop request did not end the heartbeat"
```

**Block 4: the silence check reads the constant**

SEARCH:
```python
    ended = _beats(marker)
    assert ended >= 2, "premise: the heartbeat had not advanced when the call ended"
    await asyncio.sleep(1.0)
    assert _beats(marker) == ended, "a descendant was still beating after the call ended"
```
REPLACE:
```python
    ended = _beats(marker)
    assert ended >= 2, "premise: the heartbeat had not advanced when the call ended"
    await asyncio.sleep(_SILENT_SECONDS)
    assert _beats(marker) == ended, "a descendant was still beating after the call ended"
```

**Block 5: the shell `_started_late_` test**

SEARCH:
```python
        # Control: with a generous deadline nothing ends the command, so its heartbeat keeps advancing.
        agent.DEFAULT_TIMEOUT = 10.0
        control = asyncio.create_task(
            agent._run_command(_spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)

        # Test: a 3.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time.
        # The teardown grace is cut to 0.5 s so that 1.0 s of pickup delay outlasts it, as a delay over the production
        # 5 s would: a worker that kept a fresh full budget instead of the shared deadline then ends after the
        # caller's backstop, which reports the timeout while the command still runs.
        agent.DEFAULT_TIMEOUT = 3.0
        agent.WORKER_TEARDOWN_GRACE = 0.5
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            result = await asyncio.wait_for(call, timeout=15)
            assert result == {"success": False, "error": "Command timed out after 3.0s"}
```
REPLACE:
```python
        # Control: with a generous deadline nothing ends the command, so its heartbeat keeps advancing.
        agent.DEFAULT_TIMEOUT = 10.0
        control = asyncio.create_task(
            agent._run_command(_spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control, lambda result: result.get("success") is True)

        # Test: a 4.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time,
        # with 3.0 s left for PowerShell, the root, the grandchild and two beats (BF-913, preventive: this 2.0 s window
        # has no recorded failure; the late-worker test's 1.0 s, the same shape, failed under gate load).
        # The teardown grace is cut to 0.5 s so that 1.0 s of pickup delay outlasts it, as a delay over the production
        # 5 s would: a worker that kept a fresh full budget instead of the shared deadline then ends after the
        # caller's backstop, which reports the timeout while the command still runs.
        agent.DEFAULT_TIMEOUT = 4.0
        agent.WORKER_TEARDOWN_GRACE = 0.5
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            result = await asyncio.wait_for(call, timeout=15)
            assert result == {"success": False, "error": "Command timed out after 4.0s"}
```

**Block 6: the late-worker test**

SEARCH:
```python
    """A worker picked up late reports the timeout at the shared deadline, not at the caller's backstop.

    The slot ends the tree at the backstop anyway, so the heartbeat stops before the call returns whichever budget
    the worker runs on; what the single deadline changes is WHEN the report arrives. A worker whose own budget
    restarted at pickup (1.0 s late) would end its tree, and the call would report, at about 3.0 s instead of
    2.0 s. The grace is 6.0 s (backstop at 8 s), so the backstop cannot be mistaken for the pickup delay.
    """
    agent = ShellCommandAgent(pool="shell")
    agent.DEFAULT_TIMEOUT = 2.0
    agent.WORKER_TEARDOWN_GRACE = 6.0
    marker = tmp_path / "marker"
    try:
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            started = time.monotonic()
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            await _heartbeat_is_running(marker, call)
            result = await asyncio.wait_for(call, timeout=15)
            elapsed = time.monotonic() - started
            assert result == {"success": False, "error": "Command timed out after 2.0s"}
            assert elapsed < 2.7, "the caller waited for the backstop, not the shared deadline"
```
REPLACE:
```python
    """A worker picked up late reports the timeout at the shared deadline, not at the caller's backstop.

    The slot ends the tree at the backstop anyway, so the heartbeat stops before the call returns whichever budget
    the worker runs on; what the single deadline changes is WHEN the report arrives. The deadline is 4.0 s and the
    executor is held for 1.0 s, which leaves 3.0 s for PowerShell, the root, the grandchild and two beats (BF-913:
    1.0 s did not hold under load). A worker whose own budget restarted at pickup would end its tree, and the call
    would report, no earlier than 5.0 s (1.0 s held plus 4.0 s); the bound 4.7 s lies between that and the 4.0 s
    deadline. The grace is 6.0 s (backstop at 10 s), later than both.
    """
    agent = ShellCommandAgent(pool="shell")
    agent.DEFAULT_TIMEOUT = 4.0
    agent.WORKER_TEARDOWN_GRACE = 6.0
    marker = tmp_path / "marker"
    try:
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            started = time.monotonic()
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            await _heartbeat_is_running(marker, call)
            result = await asyncio.wait_for(call, timeout=15)
            elapsed = time.monotonic() - started
            assert result == {"success": False, "error": "Command timed out after 4.0s"}
            assert elapsed < 4.7, "the call reported after the shared deadline (a budget restarted at pickup?)"
```

**Block 7: the red `_started_late_` test**

SEARCH:
```python
        # Control: with a generous deadline nothing ends the re-run, so its heartbeat keeps advancing.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)

        # Test: a 3.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time.
        # The teardown grace is cut to 0.5 s for the reason given in the shell agent's test.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 3.0)
        monkeypatch.setattr("probos.agents.red_team._RERUN_TEARDOWN_GRACE_S", 0.5)
```
REPLACE:
```python
        # Control: with a generous deadline nothing ends the re-run, so its heartbeat keeps advancing.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control, lambda verdict: verdict.verified is True)

        # Test: a 4.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time,
        # with 3.0 s left for the start (BF-913, preventive, as in the shell agent's test). The teardown grace is cut
        # to 0.5 s for the reason given there: a re-run whose budget restarted at pickup would return at 5.0 s or
        # later, after the backstop (4.5 s), whose verdict is "Verification error: ", not the worker's.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 4.0)
        monkeypatch.setattr("probos.agents.red_team._RERUN_TEARDOWN_GRACE_S", 0.5)
```

**Block 8: `test_shell_cancel_ends_tree`'s control**

SEARCH:
```python
        # Control: never cancelled, the same call keeps beating.
        control = asyncio.create_task(
            agent._run_command(_spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)
```
REPLACE:
```python
        # Control: never cancelled, the same call keeps beating.
        control = asyncio.create_task(
            agent._run_command(_spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control, lambda result: result.get("success") is True)
```

**Block 9: `test_redteam_outer_timeout_ends_rerun`'s control**

SEARCH:
```python
        # Control: never timed out from outside, the same re-run keeps beating.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)
```
REPLACE:
```python
        # Control: never timed out from outside, the same re-run keeps beating.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control, lambda verdict: verdict.verified is True)
```

**Block 10: `test_swe_run_command_cancel_ends_tree`'s control**

SEARCH:
```python
        # Control: never cancelled, the same call keeps beating.
        control = asyncio.create_task(tool.invoke(
            {"command": _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=False), "timeout": 20},
        ))
        await _beats_until_ended(control_marker, control)
```
REPLACE:
```python
        # Control: never cancelled, the same call keeps beating.
        control = asyncio.create_task(tool.invoke(
            {"command": _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=False), "timeout": 20},
        ))
        await _beats_until_ended(control_marker, control, lambda ran: ran.success)
```

### 7.2 `tests/test_ad1246_long_run_promotion.py`

**Block 11: M1 promotes at 2.0 s over a 50-beat child**

SEARCH:
```python
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=600.0,
        dm_agentic=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.6),
        work_items=store, threads=threads,
    )
    service = runtime.execution_long_runs
    llm = _ScriptedLLM("run_python", {"code": _beats_code(beat_file, 30), "timeout": 400})
```
REPLACE:
```python
    # BF-913: promotion at 2.0 s (at 0.6 s two loaded gates found no beat yet, beats_at_ack == 0: #1523 F-194, F-197);
    # 50 beats, at least 4.9 s of sleeps, keep the child running at the acknowledgement and 0.5 s after it.
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=600.0,
        dm_agentic=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=2.0),
        work_items=store, threads=threads,
    )
    service = runtime.execution_long_runs
    llm = _ScriptedLLM("run_python", {"code": _beats_code(beat_file, 50), "timeout": 400})
```

**Block 12: the premise bound**

SEARCH:
```python
        assert ack == _ACK_TEMPLATE.format(work_item_id=promoted.id)
        assert 1 <= beats_at_ack < 30, beats_at_ack
```
REPLACE:
```python
        assert ack == _ACK_TEMPLATE.format(work_item_id=promoted.id)
        assert 1 <= beats_at_ack < 50, beats_at_ack
```

**Block 13: the beat total**

SEARCH:
```python
        assert records[0]["success"] is True
        assert _beats(beat_file) == 30
```
REPLACE:
```python
        assert records[0]["success"] is True
        assert _beats(beat_file) == 50
```

**Block 14: the output the model read**

SEARCH:
```python
        seen = _tool_result_seen(llm)
        assert "beats done: 30" in seen
```
REPLACE:
```python
        seen = _tool_result_seen(llm)
        assert "beats done: 50" in seen
```

## 8. Tracking (tracker pairs)

**`PROGRESS.md`** (anchored on the first line and the blank line after it):

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**BF-913 (2026-10-21), part of #1523 -- the child-start-sensitive tests get windows that hold under load; each keeps the gap that tells the correct behaviour from its mutant.** Test-only. In `tests/test_bf893_process_tree.py`: the late-worker test's deadline is 4.0 s (was 2.0 s), with the executor held 1.0 s and the grace 6.0 s, and it requires the report before 4.7 s (a budget restarted at pickup reports at 5.0 s or later); the two `_started_late_` tests' deadline is 4.0 s (was 3.0 s; preventive, that window has no recorded failure), grace 0.5 s; the heartbeat control `_beats_until_ended` waits for the first beat within one 20 s budget (it allowed 0.5 s after `.started`), requires the next beat within `_SILENT_SECONDS` (1.0 s, the window the silence check uses) and requires the call's in-time result after the stop request (on the base its stop check would also pass a beater that ignored the stop file: the call's deadline kills the tree and the count is as still). In `tests/test_ad1246_long_run_promotion.py`, M1 promotes at 2.0 s (was 0.6 s) over a 50-beat child and checks `1 <= beats_at_ack < 50`. Seven tests change; none is added. No product code, gate wrapper or CI change; F-193 (`knowledge/store.py`) is its own slice. The decisions are in DECISIONS.md (BF-913); the contract is `prompts/bf-913-child-start-test-budgets.md`.

```

**`DECISIONS.md`** (the new entry goes after BF-911's, the newest of the recent run, before the heading that follows it):

SEARCH:
```markdown
- *Reversal.* Revert the BF-911 commits. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-911 commits. Nothing persisted changes.

### BF-913 -- The child-start-sensitive tests get windows that hold under load; each widened window keeps its discriminating gap (2026-10-21, part of #1523)

- *Scope.* `tests/test_bf893_process_tree.py` and `tests/test_ad1246_long_run_promotion.py` only (F-194, F-195 on #1523, the "child-start budget family"). Contract: `prompts/bf-913-child-start-test-budgets.md` (option (a') of the Architect's consult of 2026-10-21, 18:12Z).
- *Cause (the recorded failures, #1523 F-187, F-194, F-195, F-197).* Under the broad gate's parallel load (16, 12 and 8 workers in the failing runs) three windows were too short. The shell and red-team agents start every command on Windows as `powershell -NoProfile -Command` (`agents/shell_command.py:292`, `agents/red_team.py:474`): the late-worker test's 1.0 s after the release did not hold PowerShell, the Python root, the grandchild and two beats ("the call ended before the heartbeat ran", "the grandchild never started"), and the heartbeat control's fixed 0.5 s after `.started` did not hold the grandchild's first beats (`0 > 0`). AD-1246 M1 runs its child in `SubprocessSandbox`, which starts Python directly (`execution/isolation.py:1007-1038`): at the 0.6 s promotion the child had written no beat (`beats_at_ack == 0`). The two `_started_late_` windows (2.0 s after the release) have no recorded failure; widening them is preventive. The product code was correct.
- *D1.* Fix each start window and keep each discriminating gap; nothing in the gate wrapper or CI changes.
- *D2.* Late-worker test: deadline 4.0 s, hold 1.0 s, grace 6.0 s, bound 4.7 s: a budget restarted at pickup reports at 5.0 s or later.
- *D3.* `_started_late_` tests: deadline 4.0 s, hold 1.0 s, grace 0.5 s: the hold stays longer than the grace, so the red team's worker verdict ("Verification command timed out") is still told from its backstop's ("Verification error: ").
- *D4-D6.* The heartbeat control waits for the first beat within one 20 s budget and requires the next within `_SILENT_SECONDS` (1.0 s), the constant the silence check reads (not the consult's 2 s: a longer rise window would not show that a live beater advances within the window the check gives it). It requires the caller's in-time result after the stop request, so a beater that ignores the stop file fails it.
- *D7.* AD-1246 M1: promotion at 2.0 s over 50 beats; `1 <= beats_at_ack < 50`.
- *Rejected.* A marker plus a serial lane in the gate wrapper (HIGH tier, hides thin budgets; fallback only); a spawner without PowerShell (stops testing the production chain); fewer workers (every gate pays, the cause stays); a bounded retry (a real timing regression also fails only sometimes and would pass); `xdist_group` (`--dist=loadfile` already keeps a file on one worker).
- *Reversal.* Revert the BF-913 commit. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both belong to the commit. Then `--check` and `tests/test_ad1184_ad_ledger.py` (M3).

**Records the orchestrator adds before the commit** (a tracker change after the gate invalidates it): one bullet in the BF-913 DECISIONS entry, *Validation of record*, with the harness counts (base and fix, section 10) and the mutation campaign (rows killed, first failing test per row, base tree, sha256 of each file in section 9), then the ledger regeneration again.

**`docs/development/roadmap.md`:** no row. Its Bug Tracker has no row for BF-908 to BF-912 (section 11); this follows that practice.

**#1523:** the orchestrator renames F-195 to the "child-start budget family" and lists F-194, F-195, the `test_shell_cancel_ends_tree` control failure and the 2026-10-21 occurrence (the consult's filing decision); this contract edits no GitHub state.

## 9. Mutation rows (whole stripped lines; each occurs once in its file on `b72194ab`)

Group g1 runs against `tests/test_bf893_process_tree.py`, group g2 against `tests/test_ad1246_long_run_promotion.py`, each on the contract-applied tree, after an unmutated baseline run of the group's file that passes. The runner mutates each file in place and restores it before the next row.

| # | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| T1 | `src/probos/agents/shell_command.py` (`:316`) | `timeout=max(deadline - time.monotonic(), 0.0),` | `timeout=self.DEFAULT_TIMEOUT,` | `test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop`: `assert elapsed < 4.7` (the mutant reports at 5.0 s or later) |
| T2 | `src/probos/agents/red_team.py` (`:490`) | `stdout_bytes, _ = proc.communicate(timeout=max(deadline - time.monotonic(), 0.0))` | `stdout_bytes, _ = proc.communicate(timeout=_RERUN_TIMEOUT_S)` | `test_red_team_rerun_started_late_leaves_no_descendant_when_the_timeout_is_reported`: `assert verdict.discrepancy == "Verification command timed out"` (the backstop at 4.5 s answers first) |
| T3 | `src/probos/agents/shell_command.py` (`:205`) | `slot.cancel()  # BF-893: an enclosing timeout or cancellation must not leave the tree running` | `pass` | `test_shell_cancel_ends_tree`: `assert _beats(marker) == ended` in `_assert_silent_after_the_call` ("a descendant was still beating after the call ended") |
| T4 | `tests/test_bf893_process_tree.py` (`:103` on the base, `:106` after block 2) | `while time.monotonic() < end and not os.path.exists(marker + ".stop"):` | `while time.monotonic() < end:` | `test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported`: `assert in_time(result)` in `_beats_until_ended` (its control call ends at its 10 s deadline, inside the helper's 20 s wait, with `{"success": False, ...}`); the other four callers fail the same assertion |
| P1 | `src/probos/cognitive/turn_promotion.py` (`:2443`) | `done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)` | `done, _pending = await asyncio.wait({task}, timeout=0.0)` | `test_m1_long_run_promotes_keeps_running_and_reports_once`: `assert 1 <= beats_at_ack < 50` (promotion before the child's first beat) |
| P2 | same line as P1 | `done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)` | `done, _pending = await asyncio.wait({task})` | `test_m1_long_run_promotes_keeps_running_and_reports_once`: `assert len(items) == 1` (the run completes inline; no work item) |

T4 is a test-fixture row, not product code: it mutates the beater script inside the test file that g1 runs. P1's kill rests on the zero-wait promotion acknowledging (one work-item insert) before the sandboxed child's first beat (a Python start); if P1 survives, the orchestrator reports it to the Architect and does not narrow M1's window to kill it. T1 also leaves the shell `_started_late_` test passing (the slot ends the tree at its 4.5 s backstop with the same message); that is expected and why the late-worker test exists. Campaign of record: name the base tree and each file's sha256 (`shell_command.py`, `red_team.py`, `turn_promotion.py`, both test files); a later run whose hashes match does not repeat it.

## 10. Stress harness (not committed; the orchestrator runs it)

Save as `logs/bf913_stress.py` in each tree under test (`logs/` is ignored). Windows only. Run it first on a scratch tree at the base `b72194ab`, then on the contract-applied tree:

```
d:/ProbOS/.venv/Scripts/python.exe -I logs/bf913_stress.py --expect base
d:/ProbOS/.venv/Scripts/python.exe -I logs/bf913_stress.py --expect fix
```

```python
"""BF-913 stress harness (not committed): the seven child-start-sensitive tests under CPU load, N runs.

Run from the root of the tree under test. Exit codes: 0 the expectation held; 1 the fix failed at least once;
2 a run was invalid (its own premise: every run reports all seven tests, none skipped, pytest exit 0 or 1);
3 the base never failed (the harness does not model the problem).
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import sysconfig
import time
import xml.etree.ElementTree as ET
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_P = "tests/test_bf893_process_tree.py::"
TESTS = (
    _P + "test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported",
    _P + "test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop",
    _P + "test_red_team_rerun_started_late_leaves_no_descendant_when_the_timeout_is_reported",
    _P + "test_shell_cancel_ends_tree",
    _P + "test_redteam_outer_timeout_ends_rerun",
    _P + "test_swe_run_command_cancel_ends_tree",
    "tests/test_ad1246_long_run_promotion.py::test_m1_long_run_promotes_keeps_running_and_reports_once",
)
NAMES = {test.rsplit("::", 1)[1] for test in TESTS}
BURNER = "while True: pass"
_KILL_ON_JOB_CLOSE = 0x2000
_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA_AND_TERMINATE = 0x0100 | 0x0001


class _Basic(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _Io(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _Extended(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> ctypes.WinDLL:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k32


def _job(k32: ctypes.WinDLL) -> int:
    """A job that ends every process in it when its last handle closes, so the burners die with this harness."""
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
    return job


def _start_burners(k32: ctypes.WinDLL, job: int, count: int) -> list[subprocess.Popen[bytes]]:
    burners: list[subprocess.Popen[bytes]] = []
    for _ in range(count):
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", BURNER],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        burners.append(proc)
        handle = k32.OpenProcess(_PROCESS_SET_QUOTA_AND_TERMINATE, False, proc.pid)
        assigned = bool(handle) and bool(k32.AssignProcessToJobObject(job, handle))
        error = ctypes.get_last_error()
        if handle:
            k32.CloseHandle(handle)
        if not assigned:
            proc.kill()
            raise OSError(error, f"burner {proc.pid} could not join the job")
    time.sleep(1.0)
    dead = [proc.pid for proc in burners if proc.poll() is not None]
    if dead:  # premise: the load exists before the first run
        raise SystemExit(f"PREMISE FAILED: burners exited at once: {dead}")
    return burners


def _env() -> dict[str, str]:
    """The gate's interpreter environment (scripts/run_test_gate.py:812-836): this tree's src, no bytecode."""
    env = os.environ.copy()
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME"):
        env.pop(name, None)
    site_packages = str(Path(sysconfig.get_paths()["purelib"]).resolve())
    env["PYTHONPATH"] = os.pathsep.join((site_packages, str(ROOT), str(ROOT / "src")))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _run(index: int, workers: int, out_dir: Path) -> tuple[bool, list[str], float, int]:
    xml_path = out_dir / f"run-{index:02d}.xml"
    log_path = out_dir / f"run-{index:02d}.log"
    command = [
        sys.executable, "-P", "-m", "pytest", *TESTS, "-n", str(workers), "-q",
        "-p", "no:cacheprovider", f"--junitxml={xml_path}",
    ]
    started = time.monotonic()
    with log_path.open("wb") as log:
        rc = subprocess.run(command, cwd=ROOT, env=_env(), stdout=log, stderr=subprocess.STDOUT, timeout=900).returncode
    elapsed = time.monotonic() - started
    if not xml_path.exists():
        return False, [], elapsed, rc
    cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    seen = {case.get("name", "") for case in cases}
    failed = sorted({
        case.get("name", "") for case in cases
        if case.find("failure") is not None or case.find("error") is not None
    })
    skipped = [case.get("name", "") for case in cases if case.find("skipped") is not None]
    valid = seen == NAMES and not skipped and rc in (0, 1)
    return valid, failed, elapsed, rc


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("Windows only: the family is the PowerShell start chain")
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", choices=("base", "fix"), required=True)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--burners", type=int, default=24)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    out_dir = ROOT / "logs" / "bf913-stress" / f"{args.expect}-{time.strftime('%Y%m%dT%H%M%S')}"
    out_dir.mkdir(parents=True)
    k32 = _kernel32()
    job = _job(k32)
    failed_runs = invalid_runs = 0
    per_test: dict[str, int] = {}
    try:
        _start_burners(k32, job, args.burners)
        print(f"tree {ROOT}; {args.burners} burners on {os.cpu_count()} logical CPUs; -n {args.workers}", flush=True)
        for index in range(1, args.runs + 1):
            valid, failed, elapsed, rc = _run(index, args.workers, out_dir)
            invalid_runs += not valid
            failed_runs += bool(failed)
            for name in failed:
                per_test[name] = per_test.get(name, 0) + 1
            state = "ok" if valid else "INVALID"
            print(f"run {index:02d}/{args.runs} {state} rc={rc} {elapsed:.0f}s failed: {' '.join(failed) or '-'}",
                  flush=True)
    finally:
        k32.TerminateJobObject(job, 1)
        k32.CloseHandle(job)
    print(f"failed runs {failed_runs}/{args.runs}; invalid {invalid_runs}; per test {per_test}; logs {out_dir}")
    if invalid_runs:
        return 2
    if args.expect == "base":
        return 0 if failed_runs else 3
    return 1 if failed_runs else 0


if __name__ == "__main__":
    sys.exit(main())
```

The harness's own premises: the burners must be alive and in the job before the first run; each run must report exactly the seven test names, none skipped, with pytest exit 0 or 1, or the run is INVALID (exit 2); the base must fail at least once (else exit 3). The burners join the job right after they start; a harness killed in that interval can leave one burner, which `taskkill /im python.exe` would not distinguish, so look for a `-c "while True: pass"` command line if the harness was interrupted. `-n 8` overrides the `-n 16` in `addopts` (`pyproject.toml:196`); `--dist=loadfile` stays, as in the gate.

**When the base does not fail (exit 3):** rerun the base once with `--burners` at twice `os.cpu_count()` and `--workers 16`. If it still does not fail, record on #1523 and in the *Validation of record* bullet that the harness did not reproduce the family, do not cite the fix tree's runs as evidence, and continue on the derivations (section 6), the mutation rows and the broad gate. Do not tune the harness further. **When the fix fails (exit 1):** stop and bring the run lines and the failing logs to the Architect; do not widen a window without a new derivation.

## 11. Verified Against Codebase (2026-10-21, tree `b72194ab`)

```
git rev-parse --short=8 HEAD                                    -> b72194ab
git ls-files --eol PROGRESS.md DECISIONS.md tests/test_bf893_process_tree.py tests/test_ad1246_long_run_promotion.py
  i/lf w/crlf (all four)

grep -n "^def |^async def |_ON_WINDOWS|@pytest.mark.timeout|DEFAULT_TIMEOUT|WORKER_TEARDOWN_GRACE" tests/test_bf893_process_tree.py
  51:from collections.abc import Coroutine            (read)
  66:_ON_WINDOWS = sys.platform == "win32"
  78:_BEAT_LIMIT_SECONDS = 60
  103:        while time.monotonic() < end and not os.path.exists(marker + ".stop"):
  165:def _spawner_command(...)    190:    if _ON_WINDOWS:
  241-243: _stop_heartbeat: for _ in range(8): if not _beating(marker, over=0.25)
  334:async def _beats_until_ended(marker: Path, call: asyncio.Task[Any]) -> None:
  341: _appears_async(_started(marker), 20)   343: await asyncio.sleep(0.5)   344: assert _beats(marker) > first
  352:async def _heartbeat_is_running(...)  354: 20 s .started poll   355-357: 20 s poll for 2 beats, stops on call.done()
  362:async def _assert_silent_after_the_call(...)   367: await asyncio.sleep(1.0)
  725:@pytest.mark.timeout(90) 726:async def test_shell_agent_worker_started_late_...  740: 10.0  750: 3.0  751: 0.5  756: sleep(1.0)
  767:@pytest.mark.timeout(90) 768:async def test_shell_agent_late_worker_...  779: 2.0  780: 6.0  788: sleep(1.0)  795: elapsed < 2.7
  838:@pytest.mark.timeout(90) 839:async def test_red_team_rerun_started_late_...  848: 10.0  856: 3.0  857: 0.5  862: sleep(1.0)
  874:@pytest.mark.timeout(90) 875:async def test_shell_cancel_ends_tree   883: 20.0
  908:@pytest.mark.timeout(90) 909:async def test_redteam_outer_timeout_ends_rerun   923: 10.0  929: 5.0  938: < 4.5
  1111:@pytest.mark.timeout(90) 1112:async def test_swe_run_command_cancel_ends_tree   1120: "timeout": 20

grep -n "_beats_until_ended\(|_heartbeat_is_running\(|_appears_async\(|_BEAT_LIMIT_SECONDS|_spawner_command\(beater" tests/
  only tests/test_bf893_process_tree.py: _beats_until_ended at 744, 852, 891, 927, 1122;
  _heartbeat_is_running at 791, 897, 935, 1128; _appears_async at 341, 354, 722, 835, 984
grep -n "_assert_silent_after_the_call\(" tests/test_bf893_process_tree.py -> 761, 796, 868, 901, 939, 1132
grep -n "DEFAULT_TIMEOUT = |WORKER_TEARDOWN_GRACE|_RERUN_TIMEOUT_S|_RERUN_TEARDOWN_GRACE_S" tests/
  only tests/test_bf893_process_tree.py (422, 430, 609, 616, 701, 711, 740, 750, 751, 779, 780, 814, 823, 848, 856, 857,
  883, 923, 929, 1013, 1014, 1030, 1031)

src/probos/agents/shell_command.py
  70:    WORKER_TEARDOWN_GRACE: float = 5.0
  196:        deadline = time.monotonic() + self.DEFAULT_TIMEOUT
  199-201: wait_for(run_in_executor(None, self._run_sync, command, deadline, slot), timeout=DEFAULT_TIMEOUT + WORKER_TEARDOWN_GRACE)
  205:            slot.cancel()  # BF-893: an enclosing timeout or cancellation must not leave the tree running
  208:            slot.cancel()
  286:        if time.monotonic() >= deadline or (slot is not None and slot.cancelled()):
  292:                args = ["powershell", "-NoProfile", "-Command", command]
  316:                        timeout=max(deadline - time.monotonic(), 0.0),
  320:                    tree.kill()
src/probos/agents/red_team.py
  31:_RERUN_TIMEOUT_S = 5.0    32:_RERUN_TEARDOWN_GRACE_S = 5.0
  318: deadline = time.monotonic() + _RERUN_TIMEOUT_S   326: timeout=_RERUN_TIMEOUT_S + _RERUN_TEARDOWN_GRACE_S
  328-330: except (CancelledError, TimeoutError): slot.cancel(); raise   339: discrepancy="Verification command timed out"
  395-402: except Exception as e: ... discrepancy=f"Verification error: {e}"
  474: args = ["powershell", "-NoProfile", "-Command", command]
  490:                    stdout_bytes, _ = proc.communicate(timeout=max(deadline - time.monotonic(), 0.0))
  493:                    tree.kill()
src/probos/cognitive/swe_harness/tools.py
  1331-1336: except TimeoutError: tree.kill(); return ToolResult(error=f"run_command timed out after {timeout}s", ...)
src/probos/tools/protocol.py:90-91: def success(self) -> bool: return self.error is None
src/probos/cognitive/turn_promotion.py
  2442: _wait_started = time.monotonic()
  2443:    done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)
  2445-2448: if task in done: return task.result()

tests/test_ad1246_long_run_promotion.py
  227: def _beats_code(beat_file: Path, beats: int) -> str:   229: assert beats <= 50
  270: async def test_m1_long_run_promotes_keeps_running_and_reports_once(   (no decorator, read 265-270)
  278: promote_to_task_after_seconds=0.6   282: _beats_code(beat_file, 30)   285: wait_for(..., timeout=10)
  293: assert 1 <= beats_at_ack < 30   296-297: sleep(0.5); _beats > beats_at_ack   315: == 30   324: "beats done: 30"
grep -n "== 30|beats done: 30|< 30" -> 293, 315, 324 (and 512, "== 300.0", not a match of these lines)
grep -n "promote_to_task_after_seconds" tests/test_ad1246_long_run_promotion.py -> 278, 351, 399, 475, 528, 609

pyproject.toml:190 timeout = 180    :196 addopts = "-n 16 --dist=loadfile"
scripts/run_test_gate.py:812-836 the gate's PYTHONPATH (site-packages, repo, src)
.gitignore:121 /logs/*
PROGRESS.md:1 "# ProbOS Progress" (count 1), :2 blank, :3 the BF-911 entry
DECISIONS.md:469 "### BF-911 -- ..."; :484 "- *Reversal.* Revert the BF-911 commits. ..." (count 1);
  :486 "### Explicit delegation models, plain-id profile models and the orchestrator's model guard (...)"
scripts/gen_ad_ledger.py:28-31 "--check ... is what tests/test_ad1184_ad_ledger.py runs"

BF number: git log --all subjects: highest BF-911; prompts/bf-91*: bf-910, bf-911; gh issue list (all states):
  #1615 "BF-912: ...", no BF-913 or higher. BF-913 is free.
```

## Absence Verified (2026-10-21)

```
CLAIM: no other test file calls the bf893 helpers or sets these constants
RUN:   Grep "_beats_until_ended\(|_heartbeat_is_running\(|_appears_async\(|_BEAT_LIMIT_SECONDS" tests/
       Grep "DEFAULT_TIMEOUT = |WORKER_TEARDOWN_GRACE|_RERUN_TIMEOUT_S|_RERUN_TEARDOWN_GRACE_S" tests/
FOUND: only tests/test_bf893_process_tree.py (lines in section 11)
HOLDS: yes. The search can find: it found every caller in the one file.

CLAIM: no test pins the text of the two edited test files (no source-scan test)
RUN:   Grep "test_bf893_process_tree|test_ad1246_long_run_promotion" (repo, prompts/ excluded)
FOUND: tests/fixtures/file_durations.json:226 (a duration, ad1246), tests/test_ad1246_long_run_units.py:4 (a docstring),
       tests/test_issue1417_run_python_child_ownership.py:273 (a comment); PROGRESS.md, DECISIONS.md, the two input files
HOLDS: yes: none reads the files' lines.

CLAIM: none of the seven tests is skipped on a platform
RUN:   Grep "@pytest.mark.timeout|skipif" decorators in tests/test_bf893_process_tree.py (section 11); Read ad1246 :265-270
FOUND: skipif only at :512 and :539/:555 (tests not in this contract); the six bf893 tests carry only timeout(90); M1 none
HOLDS: yes

CLAIM: the base's control stop check passes when the beater ignores the stop file
RUN:   Read tests/test_bf893_process_tree.py:334-349; shell_command.py:315-322; red_team.py:489-494; tools.py:1328-1336
FOUND: after wait_for(call) returns, the call ended either because the grandchild stopped or because the worker's
       deadline called tree.kill(); in both the count is still at :347-349
HOLDS: yes by reading; row T4 is the empirical check (it must be killed by the new assertion on the applied tree)

CLAIM: pytest-repeat is not installed (the harness loops itself)
RUN:   Glob pytest_repeat* in d:/ProbOS/.venv/Lib/site-packages; control: Glob pytest_timeout* in the same directory
FOUND: no pytest_repeat; pytest_timeout.py found (the glob can find a plugin)
HOLDS: yes

CLAIM: the roadmap Bug Tracker has no row for BF-908 to BF-913
RUN:   Grep "BF-91[0-3]|BF-90[89]" docs/development/roadmap.md (count)
FOUND: 0. Control: the same pattern finds BF-911 and BF-910 in git subjects and prompts/
HOLDS: yes
```

## 12. What this does NOT change, and what I could not verify

**Not changed:** any file under `src/`; `scripts/run_test_gate.py`, `scripts/_gate_pytest_plugin.py`; CI; `pyproject.toml`; `_heartbeat_is_running`; every other test in both files; F-193 (`knowledge/store.py`).

**Deterministic gate checks.** The architecture (layer and import), seam-registry (AD-1343 M0), store-registry and config-facade checks read `src/` and `config/`; this change touches neither, so they see the same inputs as on the base. The ledger check (`tests/test_ad1184_ad_ledger.py`, `gen_ad_ledger.py --check`) is reached, by the `PROGRESS.md` and `DECISIONS.md` edits: hence the regeneration in M3. I ran none of these and no test (the bridge allows no state-changing run).

**Considered, deferred (same shape, not in the evidence):** `test_redteam_outer_timeout_ends_rerun`'s `< 4.5` (`:938`) counts the heartbeat's start from `started_at` (`:931`), so a start over 3.5 s fails it; it is in the harness, so a failure there will show. `test_shell_agent_timeout_ends_the_grandchild` needs `.started` within its 4.0 s deadline (`:616-620`); not in the harness. `_heartbeat_is_running` keeps polling `.started` for 20 s after its call ended (`:354`), which lengthens a failing run only. The red `_started_late_` test keeps the base's 0.5 s teardown room before its backstop.

**Could not verify here:** the idle start-chain times (0.38-0.66 s) are the consult's, not re-measured; why a start is slow under load (the failures record that each window was too short, not why); that P1 is killed (section 9 says what to do if not); `src/probos/execution/process_tree.py` was not read (no number here depends on it beyond `tree.kill()` ending the tree, which BF-893's own tests pin).

**Prior art:** not applicable: a test-only BF on ProbOS's own timing windows, not a capability or design AD.

## 13. Diff Reviewer: properties to verify

1. The late-worker test's bound (4.7 s) is below the earliest report of a worker whose budget restarted at pickup (hold 1.0 s + deadline 4.0 s) and above the deadline; its backstop (4.0 + 6.0 s) is later than both.
2. In each `_started_late_` test the hold (1.0 s) is longer than the grace (0.5 s), so a restarted budget ends after the backstop; the red-team test's verdict assertion still separates the worker's verdict from the backstop's.
3. The control's rise window equals the silence check's window (`_SILENT_SECONDS`), and both read the constant.
4. No premise became an assertion that holds whatever the code does: the control's in-time assertion fails when the stop file is ignored (row T4); `1 <= beats_at_ack` fails on a promotion before the first beat (P1); `beats_at_ack < 50` fails if the child had finished.
5. Every changed poll is bounded, and each test's sum of poll caps is at most the base's and under its timeout: `@pytest.mark.timeout(90)` for the six `tests/test_bf893_process_tree.py` tests; M1 has no marker and runs under the configured global `timeout = 180` (`pyproject.toml:190`), with 30.5 s of caps (section 6).
6. The callers of each changed helper keep their own windows: the five `_beats_until_ended` callers keep their control deadlines (10, 10, 20, 10, 20 s); the six `_assert_silent_after_the_call` callers keep 1.0 s; no other test's `DEFAULT_TIMEOUT`, grace or `_RERUN_*` value changed.
7. Each `in_time` predicate accepts that site's success result and refuses its timeout result (`{"success": False, ...}`; `verified is False`; `ToolResult.error` set).
8. Nothing outside the two test files, the two trackers and the two generated ledger files changed.

## 14. Acceptance criteria

1. The 14 blocks of section 7 apply on `b72194ab`, each SEARCH matching once.
2. `tests/test_bf893_process_tree.py` and `tests/test_ad1246_long_run_promotion.py` pass at `-n 0` on Windows.
3. The harness (section 10) fails at least once on the base and 0 of 30 on the fix, or the base's non-reproduction is recorded as section 10 says.
4. Rows T1-T4, P1 and P2 are killed by the named assertions (P1: section 9).
5. The trackers carry BF-913 as in section 8, the ledger files are regenerated, and `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass.
6. One receipted broad gate, green, on the committed tree.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-10-21, review round 1, F1)

**F1 (P3):** the rationale stated inferred failures as observed and gave M1 the PowerShell launch chain. **Evidence re-read on #1523:** late-worker F-83 and F-195 (`:358`, "the call ended before the heartbeat ran"; the BF-911 first gate, "the grandchild never started"); control F-187 and the BF-911 first gate (`:344`, `0 > 0`); M1 F-194 and F-197 (`:293`, `beats_at_ack == 0`); the `_started_late_` windows: no failure. So the M1 cause is recorded (sections 1 and 12 had said it was not), and the `_started_late_` widening is preventive.

**Changed (comments and Markdown only):** the `_started_late_` comments say "preventive"; the M1 comment cites F-194 and F-197; the DECISIONS *Cause* names the recorded failures and restricts the PowerShell chain to the shell and red-team tests (M1: `SubprocessSandbox`, `python -I -B`, `isolation.py:1007-1038`; SWE `run_command`: `create_subprocess_shell`, `tools.py:1316`); PROGRESS says "preventive" and that the base stop check "would" pass an ignoring beater; sections 1, 2, 6, 12 and 13 match, and section 13 property 5 and section 6 give M1's timeout (no marker, global 180 s, 30.5 s of caps). A passing control is faster; a failing one now waits up to its call's deadline for a first beat, where it waited 0.5 s.

**Not changed:** the executable code of both test files (only `#` comment lines change; no docstring or string constant: the AST is identical), every number in sections 3 to 10, the mutation rows (section 9), the stress harness (section 10, including its message at its `SystemExit`), the trackers' headings and D-bullets, product code.
