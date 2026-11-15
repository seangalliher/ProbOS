# BF-981: the child-start premises get start windows that hold under gate load; the long-run cancel premise is polled

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-15
**Status:** ready to build. **Owning issue:** #1523 (item recorded in comment 6894100838). Commits say `Refs #1523.`
**Dependencies:** none. Build on the base after batch 1 (#1799, #1802, #1805) merges; batch 1 touches neither test file (`git diff --stat aee4a43c 27323e47`). The tracker pairs anchor on text batch 1 does not change.
**Estimated tests:** 0 new, 0 removed, 7 changed (6 in `tests/test_bf893_process_tree.py`, 1 in `tests/test_ad1246_long_run_promotion.py`).
**Test-only.** No file under `src/`, `scripts/`, `.github/` or any pytest/CI configuration changes.

## 1. Problem

Batch 1's frozen candidate `27323e47` lost two canonical gates in a row (3 workers, quiet host), each to one test whose PREMISE is that a child process has started within a fixed window:

- Attempt 1 (2026-11-15 07:50Z-09:30Z): `test_bf893_process_tree.py::test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported` failed at `:776` -> `:377`: `premise: the grandchild did not exist when the call ended`. The window: a 4.0 s deadline with the executor held 1.0 s, so 3.0 s for PowerShell, the Python root, the grandchild and two beats.
- Attempt 2 (09:58Z-11:38Z): `test_ad1246_long_run_promotion.py::test_m2_bf733_cancel_kills_the_long_child_and_the_report_is_true` failed at `:494`: `assert 0 > 0` after promotion at 0.6 s and a fixed `asyncio.sleep(0.5)`: the `run_python` child had written no beat about 1.1 s in.
- Both pass alone 3 of 3. An earlier session recorded a third sibling, `test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop` ("load flake; passes alone 3 of 3"); which of its assertions failed was not recorded.
- Idle-host probe (orchestrator, n=12): `powershell.exe -NoProfile -Command exit` median 0.37 s, max 1.10 s; `python -c pass` median 0.29 s, max 1.70 s. The chain launches PowerShell, then the Python root, then the grandchild's Python, so the sum of those idle maxima is 4.5 s (1.10 + 1.70 + 1.70), above the 3.0 s window; the chain was not timed end to end, so 4.5 s is a sum of per-launch maxima, not a measured chain maximum. Defender real-time protection is on.
- The product code is not implicated: the candidate changes no process code, and both failures are `premise:` assertions, not verdicts.

This is the family BF-913 (`cf87c720`) and BF-951 (`cb6d61ef`) fixed, both part of #1523. Each fixed only the tests that had failed. BF-913 raised the `_started_late_` windows from 2.0 s to 3.0 s, preventively; one of them has now failed at 3.0 s. M2 was missed by both: BF-913 fixed M1 (`:276`), BF-951 fixed `test_issue1417_*`.

## 2. Solution overview

Two shapes, two fixes. Each keeps the gap that tells the correct behaviour from its mutant.

- **Shape A: the premise sits before the timed part (M2).** Poll it, up to a limit that ends before the timed part begins. M2's timed part is the BF-733 watchdog's cancellation. Its clock starts when the reporter arms `_PromotedRunSupervisor`, after the promotion's work item exists (section 10). Keep promotion at 0.6 s, raise `promoted_run_deadline_seconds` from 1.0 to 3.0, and replace the fixed `sleep(0.5)`-then-assert with the file's existing `_wait_until`, limited to 2.5 s. A timeout there fails with a `premise:` message.
- **Shape B: the child must start inside the timed window (six bf893 tests).** Polling cannot help, because the deadline is the behaviour under test. Widen the start budget (deadline minus hold) to 7.0 s, which covers the 4.5 s sum of the PowerShell chain's per-launch idle maxima with 2.5 s to spare, and re-derive each window so its discriminating inequality still holds (section 6).

Rejected, one line each:
- A bounded retry of the scenario on an unmet premise. BF-913's reason still holds: a real timing regression also fails only sometimes. It becomes the next step only if 7.0 s fails under load.
- A gate-level rerun rule. That weakens the gate, so it is the Captain's decision and is being asked separately.
- Fewer workers. Every gate would pay, and the cause would stay.
- A shared cross-file helper. The two shapes need different fixes.
- Raising `_beats_code`'s 50-beat cap. Not needed: the margins in section 6 hold within 50 beats.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Start budget 7.0 s for every shape-B window | Covers the sum of the PowerShell chain's per-launch idle maxima, 4.5 s (1.10 + 1.70 + 1.70), with 2.5 s to spare; the chain was not timed end to end. 3.0 s failed under load; BF-913's 4.0 s timeouts have no recorded failure but are the same chain |
| D2 | Late-worker report test: deadline 9.0 s, hold 2.0 s, grace 6.0 s, bound `elapsed < 10.0` | Start budget 7.0 s. The bound sits 1.0 s from the correct report (was 0.7 s) and 1.0 s from the mutant's earliest (was 0.3 s). Backstop 15.0 s is later than the mutant's 11.0 s |
| D3 | `_started_late_` tests (shell, red team): deadline 8.0 s, hold 1.0 s, grace 0.5 s | Start budget 7.0 s. Hold 1.0 s stays longer than grace 0.5 s, so the red team's worker verdict is still told apart from its backstop's |
| D4 | Timeout tests (`run_command`, shell agent, red team): timeout 7.0 s, grandchild delay 10 s, "never appears" window 11 s | Keeps the module docstring's margins: the grandchild outlives the timeout by 3 s, and the window (11) spans its whole sleep (10). Red team: `_RERUN_TIMEOUT_S` monkeypatched from 5.0 to 7.0, read at call time (`red_team.py:488`) |
| D5 | M2: promotion 0.6 s (kept), deadline 3.0 s from the promotion, premise polled up to 2.5 s | The poll ends before the cancellation. The child's 50 beats take at least 4.9 s of sleeps, so it outlives the cancellation (about 3.6 s after the turn starts) plus the 1.0 s stop check, on both the correct tree and the R1 mutant |

## 4. Milestones and commits

- **M1** `tests/test_bf893_process_tree.py`: pairs P1-1 to P1-7.
  Commit subject: `Process-tree tests give a child's start 7.0 s under gate load and keep each discriminating gap`
  Body: one paragraph from sections 1 and 3 (D1-D4), then `Refs #1523.`
- **M2** `tests/test_ad1246_long_run_promotion.py`: pairs P2-1 and P2-2.
  Commit subject: `Long-run cancel test polls for the child's beat after the acknowledgement, before the watchdog's deadline`
  Body: one paragraph from section 3 (D5), then `Refs #1523.`
- **M3** trackers: pairs P3-1 and P3-2, then `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` (no `--online`). This regenerates `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`; stage both.
  Commit subject: `Trackers for the child-start windows widened under gate load`
  Body: `Refs #1523.`

No subject carries an `AD-` or `BF-` token. Never `git add -A`; stage the named files only.

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py` (M3), run `git diff --check` and `git diff --stat`, and commit per section 4.
- **May not:** run pytest (the orchestrator runs every test), edit any file not named here, change product code, add `skip`/`xfail`/retry, or reword a SEARCH anchor. If a SEARCH does not match exactly once, stop and report.

## 6. Each window's derivation (shape B and M2)

| Window | Correct side | Mutant side | Gap |
|---|---|---|---|
| Late-worker, `elapsed < 10.0` | communicate's budget ends at the shared 9.0 s deadline; tree kill and return follow, with 1.0 s of room | T1: budget restarted at pickup; pickup is at least 2.0 s after `started`, so the report is at 11.0 s or later | 10.0 against 11.0 or later; backstop 9.0 + 6.0 = 15.0, later than both |
| Late-worker start | 9.0 - 2.0 = 7.0 s for PowerShell, the root, the grandchild and two beats (`_heartbeat_is_running` requires `not call.done()`) | -- | D1 |
| Shell `_started_late_` | worker ends the tree at 8.0 s and reports; silence checked after | does not tell T1 apart (the slot ends the tree at the backstop), as before | hold 1.0 > grace 0.5 |
| Red `_started_late_`, verdict | worker returns `None` at 8.0 s, before the backstop at 8.5 s: "Verification command timed out" | T2: worker returns at 9.0 s or later; backstop at 8.5 s answers "Verification error: " | 8.5 against 9.0 or later; correct side keeps 0.5 s of teardown room (unchanged) |
| Timeout tests | timeout 7.0 s; the grandchild writes its marker 10 s after its own start | a tree kill that ends only the shell (R2): the marker appears by 7.0 + 10 = 17.0 s at the latest | window 11 s from the return (about 7.0 s) reaches 18.0 s or later, at least 17.0 |
| M2 premise poll | the child's first beat after the ack, within 2.5 s; the deadline fires 3.0 s after the arm, which is at or before the ack | -- | 0.5 s between the poll limit and the cancellation, less the store read between the ack and the poll |
| M2 stop check (`:506-507`) | cancellation at about 3.6 s after the turn starts; the child is killed; no beat in the next 1.0 s | R1: kill switch not fired; the child keeps beating until at least start + 4.9 s (about 5.1 s or later); report at about 3.7 s, check window about 3.7-4.7 s | the child is still beating in the window under R1, whatever its start time (start >= 0 means end >= 5.1 > 4.7) |
| M2 `beats_at_report < 50`, `len(llm.requests) == 1` | the child cannot finish 50 beats (at least 4.9 s) before the cancellation at about 3.6 s | -- | at least 1.5 s |

## 7. The contract

### 7.1 `tests/test_bf893_process_tree.py` (M1)

**P1-1** (`tests/test_bf893_process_tree.py`: run_command timeout test, 7.0 s timeout, 10 s grandchild, 11 s window)

SEARCH:
```python
    marker = tmp_path / "marker"
    result = await tool.invoke(
        {"command": _spawner_command(spawner, marker, 7, powershell=False), "timeout": 4.0},
    )
    assert result.error == "run_command timed out after 4.0s"
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    assert not marker.exists(), "premise: the grandchild had already written its marker when the timeout fired"
    assert not await asyncio.to_thread(_appears, marker, 10), _SURVIVED
```

REPLACE:
```python
    # BF-981: 7.0 s for cmd.exe, the root and the grandchild to start before the timeout (preventive: this 4.0 s
    # window has no recorded failure; a PowerShell start chain failed a 3.0 s window under gate load). The
    # grandchild still outlives the timeout by 3 s, and the window spans its whole sleep.
    marker = tmp_path / "marker"
    result = await tool.invoke(
        {"command": _spawner_command(spawner, marker, 10, powershell=False), "timeout": 7.0},
    )
    assert result.error == "run_command timed out after 7.0s"
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    assert not marker.exists(), "premise: the grandchild had already written its marker when the timeout fired"
    assert not await asyncio.to_thread(_appears, marker, 11), _SURVIVED
```

**P1-2** (`tests/test_bf893_process_tree.py`: shell agent timeout test, 7.0 s timeout, 10 s grandchild, 11 s window)

SEARCH:
```python
    agent.DEFAULT_TIMEOUT = 4.0
    marker = tmp_path / "marker"
    result = await agent._run_command(_spawner_command(spawner, marker, 7, powershell=_ON_WINDOWS))
    assert result == {"success": False, "error": "Command timed out after 4.0s"}
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    # The worker enforces the shared deadline itself: its communicate() budget ends at that deadline, it kills the
    # tree and only then returns its own timeout result. The caller's wait_for is a later backstop (deadline +
    # WORKER_TEARDOWN_GRACE), so the tree is already gone when this call returns; the whole window is still
    # polled for a marker that must never come.
    assert not await asyncio.to_thread(_appears, marker, 10), _SURVIVED
```

REPLACE:
```python
    # BF-981: 7.0 s for PowerShell, the root and the grandchild to start before the timeout (preventive, as in the
    # run_command test); the grandchild outlives the timeout by 3 s, and the window spans its whole sleep.
    agent.DEFAULT_TIMEOUT = 7.0
    marker = tmp_path / "marker"
    result = await agent._run_command(_spawner_command(spawner, marker, 10, powershell=_ON_WINDOWS))
    assert result == {"success": False, "error": "Command timed out after 7.0s"}
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    # The worker enforces the shared deadline itself: its communicate() budget ends at that deadline, it kills the
    # tree and only then returns its own timeout result. The caller's wait_for is a later backstop (deadline +
    # WORKER_TEARDOWN_GRACE), so the tree is already gone when this call returns; the whole window is still
    # polled for a marker that must never come.
    assert not await asyncio.to_thread(_appears, marker, 11), _SURVIVED
```

**P1-3** (`tests/test_bf893_process_tree.py`: red team timeout test takes monkeypatch and a 7.0 s limit)

SEARCH:
```python
async def test_red_team_rerun_timeout_ends_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """The red team's re-run ends the grandchild when it times out (limit ``_RERUN_TIMEOUT_S``, 5 s). Kills M16."""
    # Control: left alone, the grandchild finishes inside the limit and writes its marker.
```

REPLACE:
```python
async def test_red_team_rerun_timeout_ends_the_grandchild(
    tmp_path: Path, spawner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The red team's re-run ends the grandchild when it times out. Kills M16.

    The limit is ``_RERUN_TIMEOUT_S``: 5 s in production, 7.0 s here (BF-981, preventive: PowerShell, the root and
    the grandchild start inside it under gate load; the same start chain failed a 3.0 s window).
    """
    monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 7.0)
    # Control: left alone, the grandchild finishes inside the limit and writes its marker.
```

**P1-4** (`tests/test_bf893_process_tree.py`: red team timeout test, grandchild delay 10 s; the 11 s window already spans it)

SEARCH:
```python
    marker = tmp_path / "marker"
    rerun = await asyncio.to_thread(
        RedTeamAgent._run_verify_sync,
        _spawner_command(spawner, marker, 8, powershell=_ON_WINDOWS), build_command_env(),
    )
```

REPLACE:
```python
    marker = tmp_path / "marker"
    rerun = await asyncio.to_thread(
        RedTeamAgent._run_verify_sync,
        _spawner_command(spawner, marker, 10, powershell=_ON_WINDOWS), build_command_env(),
    )
```

**P1-5** (`tests/test_bf893_process_tree.py`: shell `_started_late_` test, 8.0 s deadline)

SEARCH:
```python
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
            await _assert_silent_after_the_call(marker)
```

REPLACE:
```python
        # Test: an 8.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in
        # time, with 7.0 s left for PowerShell, the root, the grandchild and two beats (BF-981: 3.0 s failed under
        # gate load, "the grandchild did not exist when the call ended"; BF-913 had raised it from 2.0 s).
        # The teardown grace is cut to 0.5 s so that 1.0 s of pickup delay outlasts it, as a delay over the production
        # 5 s would: a worker that kept a fresh full budget instead of the shared deadline then ends after the
        # caller's backstop, which reports the timeout while the command still runs.
        agent.DEFAULT_TIMEOUT = 8.0
        agent.WORKER_TEARDOWN_GRACE = 0.5
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            result = await asyncio.wait_for(call, timeout=15)
            assert result == {"success": False, "error": "Command timed out after 8.0s"}
            await _assert_silent_after_the_call(marker)
```

**P1-6** (`tests/test_bf893_process_tree.py`: late-worker report test, deadline 9.0 s, hold 2.0 s, bound 10.0 s)

SEARCH:
```python
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

REPLACE:
```python
    the worker runs on; what the single deadline changes is WHEN the report arrives. The deadline is 9.0 s and the
    executor is held for 2.0 s, which leaves 7.0 s for PowerShell, the root, the grandchild and two beats (BF-913:
    1.0 s did not hold under load; BF-981: the same chain failed a 3.0 s window). A worker whose own
    budget restarted at pickup would end its tree, and the call would report, no earlier than 11.0 s (2.0 s held
    plus 9.0 s); the bound 10.0 s lies 1.0 s from that and 1.0 s from the deadline. The grace is 6.0 s (backstop at
    15 s), later than both.
    """
    agent = ShellCommandAgent(pool="shell")
    agent.DEFAULT_TIMEOUT = 9.0
    agent.WORKER_TEARDOWN_GRACE = 6.0
    marker = tmp_path / "marker"
    try:
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            started = time.monotonic()
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(2.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            await _heartbeat_is_running(marker, call)
            result = await asyncio.wait_for(call, timeout=15)
            elapsed = time.monotonic() - started
            assert result == {"success": False, "error": "Command timed out after 9.0s"}
            assert elapsed < 10.0, "the call reported after the shared deadline (a budget restarted at pickup?)"
```

**P1-7** (`tests/test_bf893_process_tree.py`: red team `_started_late_` test, 8.0 s deadline)

SEARCH:
```python
        # Test: a 4.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time,
        # with 3.0 s left for the start (BF-913, preventive, as in the shell agent's test). The teardown grace is cut
        # to 0.5 s for the reason given there: a re-run whose budget restarted at pickup would return at 5.0 s or
        # later, after the backstop (4.5 s), whose verdict is "Verification error: ", not the worker's.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 4.0)
        monkeypatch.setattr("probos.agents.red_team._RERUN_TEARDOWN_GRACE_S", 0.5)
```

REPLACE:
```python
        # Test: an 8.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in
        # time, with 7.0 s left for the start (BF-981, as in the shell agent's test). The teardown grace is cut to
        # 0.5 s for the reason given there: a re-run whose budget restarted at pickup would return at 9.0 s or
        # later, after the backstop (8.5 s), whose verdict is "Verification error: ", not the worker's.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 8.0)
        monkeypatch.setattr("probos.agents.red_team._RERUN_TEARDOWN_GRACE_S", 0.5)
```

### 7.2 `tests/test_ad1246_long_run_promotion.py` (M2)

**P2-1** (`tests/test_ad1246_long_run_promotion.py`: M2's BF-733 deadline 3.0 s, counted from the promotion)

SEARCH:
```python
        dm_agentic=DmAgenticConfig(
            enabled=True, promote_to_task_after_seconds=0.6, promoted_run_deadline_seconds=1.0,
        ),
```

REPLACE:
```python
        # BF-981: the watchdog's 3.0 s (was 1.0 s) counts from the promotion, when the reporter arms
        # _PromotedRunSupervisor; it leaves the premise below 2.5 s to see a beat and still ends the run long
        # before its 50 beats (at least 4.9 s of sleeps) can finish.
        dm_agentic=DmAgenticConfig(
            enabled=True, promote_to_task_after_seconds=0.6, promoted_run_deadline_seconds=3.0,
        ),
```

**P2-2** (`tests/test_ad1246_long_run_promotion.py`: M2's premise is polled within the deadline, failing as a premise)

SEARCH:
```python
        # Premise: the long child is still running after the acknowledgement.
        await asyncio.sleep(0.5)
        assert _beats(beat_file) > beats_at_ack
```

REPLACE:
```python
        # Premise: the long child is still running after the acknowledgement. BF-981: polled, not read after a
        # fixed 0.5 s (a loaded gate found no beat 1.1 s into the turn, 0 > 0). The 2.5 s limit ends before the
        # watchdog's 3.0 s, so a child too slow to start fails here instead of passing the stop check vacuously.
        try:
            await _wait_until(lambda: _beats(beat_file) > beats_at_ack, timeout=2.5)
        except asyncio.TimeoutError:
            pytest.fail("premise: the long child wrote no beat after the acknowledgement")
```

### 7.3 Trackers (M3)

**P3-1** (`PROGRESS.md`: BF-981 entry at the top)

SEARCH:
```markdown
# ProbOS Progress
```

REPLACE:
```markdown
# ProbOS Progress

**BF-981 (2026-11-15), part of #1523 -- the child-start premises of the process-tree and long-run tests get windows that hold under gate load; each keeps the gap that tells the correct behaviour from its mutant.** Test-only. Two canonical gates of batch 1 (#1799, #1802, #1805) each lost one test of this family, each on a `premise:` assertion that a child had started (a 3.0 s start window, then a fixed 0.5 s sleep 1.1 s into the turn); both pass alone. In `tests/test_bf893_process_tree.py` every start window becomes 7.0 s: the two `_started_late_` tests get an 8.0 s deadline (hold 1.0 s, grace 0.5 s); the late-worker report test gets 9.0 s, a 2.0 s hold and the bound `elapsed < 10.0` (a budget restarted at pickup reports at 11.0 s or later; backstop 15.0 s); the `run_command`, shell agent and red team timeout tests get a 7.0 s limit, a 10 s grandchild and an 11 s window (the red team's 5 s limit is monkeypatched). In `tests/test_ad1246_long_run_promotion.py`, M2's BF-733 deadline is 3.0 s from the promotion (was 1.0 s) and its premise polls up to 2.5 s for a beat after the acknowledgement, failing as a premise. Seven tests change; none is added. No product code, gate wrapper or CI change. The decisions are in DECISIONS.md (BF-981); the contract is `prompts/bf-981-load-flake-premises.md`.
```

**P3-2** (`DECISIONS.md`: BF-981 entry beside BF-913)

SEARCH:
```markdown
- *Reversal.* Revert the BF-913 commit. Nothing persisted changes.

### BF-900 -- The dispatch claim no longer undoes a park made in the same run (2026-10-21, #1573)
```

REPLACE:
```markdown
- *Reversal.* Revert the BF-913 commit. Nothing persisted changes.

### BF-981 -- The child-start premises get windows that hold under gate load; the long-run cancel premise is polled (2026-11-15, part of #1523)

- *Scope.* `tests/test_bf893_process_tree.py` (six tests) and `tests/test_ad1246_long_run_promotion.py` (M2) only. Contract: `prompts/bf-981-load-flake-premises.md`.
- *Cause (measured).* Two canonical gates of one unchanged candidate (3 workers, quiet host) each failed one `premise:` assertion: the shell `_started_late_` test's 3.0 s start window ("the grandchild did not exist when the call ended"), then AD-1246 M2's fixed 0.5 s after a 0.6 s promotion (`0 > 0`). An idle host starts PowerShell in up to 1.10 s and Python in up to 1.70 s (n=12), and the chain launches PowerShell and then Python twice, so the sum of those idle maxima, 4.5 s, already exceeds 3.0 s (the chain was not timed end to end). The product code was not implicated. BF-913 and BF-951 had each fixed only the tests that had failed.
- *D1.* A premise before the timed part is polled (M2); a start inside the timed window gets a 7.0 s budget, 2.5 s more than the 4.5 s sum of the chain's per-launch idle maxima.
- *D2-D4.* Late-worker: deadline 9.0 s, hold 2.0 s, grace 6.0 s, bound 10.0 s. `_started_late_`: deadline 8.0 s, hold 1.0 s, grace 0.5 s. Timeout tests: limit 7.0 s, grandchild 10 s, window 11 s.
- *D5.* M2: promotion 0.6 s, deadline 3.0 s from the promotion (the reporter arms the supervisor after the work item exists), premise polled up to 2.5 s.
- *Rejected.* A bounded retry on an unmet premise (BF-913's reason holds; the next step only if 7.0 s fails under load); a gate-level rerun rule (a Captain decision, asked separately); fewer workers; a shared cross-file helper (the two shapes need different fixes).
- *Reversal.* Revert the BF-981 commits. Nothing persisted changes.

### BF-900 -- The dispatch claim no longer undoes a park made in the same run (2026-10-21, #1573)
```

The orchestrator appends a `*Validation of record.*` bullet to this entry after the campaign in section 8.3 (BF-913's precedent, `4de346bc`).

Then run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` and stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`.

## 8. Gates (the orchestrator runs all of them; the Builder runs none)

### 8.1 Base counts, before the build

Neither test file has changed since BF-913 (`git log cf87c720..HEAD` on both: empty). BF-913's recorded baselines therefore still apply on win32:
- `tests/test_bf893_process_tree.py`: 25 passed, 2 skipped (25 test functions, 2 parametrized x2, 2 POSIX-only skips).
- `tests/test_ad1246_long_run_promotion.py`: 19 passed.

### 8.2 Focused check on the built tree

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf893_process_tree.py tests/test_ad1246_long_run_promotion.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
```

Expected:
- bf893: 25 passed, 2 skipped.
- ad1246: 19 passed.
- `tests/test_ad1184_ad_ledger.py`: the base's count, all passed. It runs `gen_ad_ledger.py --check`, so it is the consumer of the tracker edits.
- The same counts as the base: no test is added, removed or renamed.

Then the seven changed tests three times each, serially:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest "tests/test_bf893_process_tree.py::test_run_command_timeout_ends_the_grandchild" "tests/test_bf893_process_tree.py::test_shell_agent_timeout_ends_the_grandchild" "tests/test_bf893_process_tree.py::test_red_team_rerun_timeout_ends_the_grandchild" "tests/test_bf893_process_tree.py::test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported" "tests/test_bf893_process_tree.py::test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop" "tests/test_bf893_process_tree.py::test_red_team_rerun_started_late_leaves_no_descendant_when_the_timeout_is_reported" "tests/test_ad1246_long_run_promotion.py::test_m2_bf733_cancel_kills_the_long_child_and_the_report_is_true" -n 0 -p no:randomly -q
```

Expected each time: 7 passed. No other test file imports either module (section 10); `tests/fixtures/file_durations.json` records `tests/test_ad1246_long_run_promotion.py` (16.5 s) and does not record `tests/test_bf893_process_tree.py`, which the scheduler (`tests/fixtures/duration_scheduler.py:7-10`) weights by its test count times the suite's mean seconds per test (5.967 s, the Diff Reviewer's measurement). No path changes, and the slice does not change the snapshot.

### 8.3 Mutation campaign (one row at a time, restored before the next; win32; on a quiet host)

Each row runs its selector with `-n 0 -p no:randomly`. Unmutated baselines are 8.2's counts. This is the campaign of record: record the tree id and the sha256 of `src/probos/agents/shell_command.py`, `src/probos/agents/red_team.py`, `src/probos/cognitive/turn_promotion.py`, `src/probos/execution/isolation.py`, `src/probos/execution/process_tree.py` and the two test files. A Builder or rerun on files with the same hashes does not repeat it; a row whose file differs is rerun, except that a difference in `tests/test_bf893_process_tree.py` confined to comment or docstring lines (shown by `git diff` against the campaign's tree) reruns no row: no row's mutant line or killing assertion is a comment (T4's mutant, `:106`, is code).

| Row | File (line on `aee4a43c`) | Original (whole stripped line) | Mutant | Selector | Expected killer |
|---|---|---|---|---|---|
| T1 | `src/probos/agents/shell_command.py` (`:319`) | `timeout=max(deadline - time.monotonic(), 0.0),` | `timeout=self.DEFAULT_TIMEOUT,` | `tests/test_bf893_process_tree.py::test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop` | `assert elapsed < 10.0` (the mutant reports at 11.0 s or later) |
| T2 | `src/probos/agents/red_team.py` (`:509`) | `stdout_bytes, _ = proc.communicate(timeout=max(deadline - time.monotonic(), 0.0))` | `stdout_bytes, _ = proc.communicate(timeout=_RERUN_TIMEOUT_S)` | `tests/test_bf893_process_tree.py::test_red_team_rerun_started_late_leaves_no_descendant_when_the_timeout_is_reported` | `assert verdict.discrepancy == "Verification command timed out"` (the backstop at 8.5 s answers first) |
| T3 | `src/probos/agents/shell_command.py` (`:208`) | `slot.cancel()  # BF-893: an enclosing timeout or cancellation must not leave the tree running` | `pass` | `tests/test_bf893_process_tree.py::test_shell_cancel_ends_tree` | `assert _beats(marker) == ended` in `_assert_silent_after_the_call` (test unchanged; confirms the module still discriminates) |
| T4 | `tests/test_bf893_process_tree.py` (`:106`) | `while time.monotonic() < end and not os.path.exists(marker + ".stop"):` | `while time.monotonic() < end:` | `tests/test_bf893_process_tree.py::test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported` | `assert in_time(result)` in `_beats_until_ended` (its control ends at its 10 s deadline with `{"success": False, ...}`) |
| P1 | `src/probos/cognitive/turn_promotion.py` (`:2477`) | `done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)` | `done, _pending = await asyncio.wait({task}, timeout=0.0)` | `tests/test_ad1246_long_run_promotion.py::test_m1_long_run_promotes_keeps_running_and_reports_once` | `assert 1 <= beats_at_ack < 50` (M1 is unchanged; rerun because the file's hash changes) |
| P2 | same line as P1 | `done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)` | `done, _pending = await asyncio.wait({task})` | same as P1 | `assert len(items) == 1` |
| R1 (new, M2) | `src/probos/execution/isolation.py` (`:715`) | `request.kill_switch.fire("cancelled")` | `pass` | `tests/test_ad1246_long_run_promotion.py::test_m2_bf733_cancel_kills_the_long_child_and_the_report_is_true` | `assert _beats(beat_file) == beats_at_report` after the 1.0 s sleep (the child keeps beating; section 6) |
| R2 (new, timeout windows) | `src/probos/execution/process_tree.py` (`:171`) | `if _win32().terminate_job(self._job, _KILLED_EXIT_CODE):` | `if False:` | the three timeout tests: `::test_run_command_timeout_ends_the_grandchild`, `::test_shell_agent_timeout_ends_the_grandchild`, `::test_red_team_rerun_timeout_ends_the_grandchild` | the `_SURVIVED` check in each (only the shell is ended, `:193`; the grandchild writes its marker inside the 11 s window). All three must fail |

R1 also has a precondition: on the UNMUTATED tree the M2 premise poll must pass. A row whose premise fails is INVALID, not killed; rerun it.

Record each row as KILLED (by the named assertion, or name the one that fired), SURVIVED or INVALID. Any survivor stops the slice for Architect triage.

### 8.4 Broad gate

Once, per the standing procedure (`scripts/run_test_gate.py --label <label> --receipt logs/gates/<label>.receipt.json`), before the next batch's gate (decision M).

## 9. Diff Reviewer: properties to verify

1. The diff touches only the two test files, `PROGRESS.md`, `DECISIONS.md` and the two regenerated ledger files. No product, script, CI or pytest configuration change.
2. Each changed window keeps the inequality in section 6:
   - late-worker: deadline < bound < hold + deadline, and deadline + grace > hold + deadline;
   - `_started_late_`: hold > grace;
   - timeout tests: delay - timeout >= 3, and window >= delay;
   - M2: poll limit < deadline, and the child's at least 4.9 s of beats outlast promotion + deadline + 1.0 s.
3. No premise became vacuous or tolerant:
   - M2's poll timeout fails through `pytest.fail` with a message starting `premise:`;
   - no `skip`, `xfail`, retry or broadened `except` was added;
   - every pre-existing `premise:` assertion is still present.
4. Each expected message matches its producer's formatting at the new value: `f"Command timed out after {self.DEFAULT_TIMEOUT}s"` (`shell_command.py:214`, `:288`) gives `8.0s`/`9.0s`/`7.0s`; `f"run_command timed out after {timeout}s"` (`swe_harness/tools.py:1393`) gives `7.0s`.
5. The monkeypatched `_RERUN_TIMEOUT_S` is read at call time on the path each test drives (`red_team.py:337`, `:488`).
6. Comments state measured causes as measured and preventive changes as preventive; no comment cites a line number.
7. The tracker entries describe the diff exactly (numbers, test count 7, none added), and `tests/test_ad1184_ad_ledger.py` passes with the regenerated ledger.
8. Every SEARCH block occurred exactly once in its file at its turn, and the files are ASCII with LF line endings.

## 10. Verified Against Codebase (2026-11-15, tree `aee4a43c`)

```
grep -n "assert _started(marker).exists(), \"premise: the grandchild did not exist when the call ended\"" tests/test_bf893_process_tree.py
  377: assert _started(marker).exists(), "premise: the grandchild did not exist when the call ended"
grep -n "^async def test_" tests/test_bf893_process_tree.py (selected)
  587: test_run_command_timeout_ends_the_grandchild   614: test_shell_agent_timeout_ends_the_grandchild
  642: test_red_team_rerun_timeout_ends_the_grandchild
  739: test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported
  783: test_shell_agent_late_worker_reports_at_the_deadline_not_the_backstop
  856: test_red_team_rerun_started_late_leaves_no_descendant_when_the_timeout_is_reported
  894: test_shell_cancel_ends_tree
tests/test_bf893_process_tree.py
  18-20: the module's stated margins (grandchild outlives the timeout by >= 3 s; window spans the sleep)
  81: _SILENT_SECONDS = 1.0   106: the beater's stop-file loop (row T4)
  597, 605: run_command test passes powershell=False (cmd.exe)
  765-766, 771, 775: shell _started_late_ 4.0 / 0.5 / sleep(1.0) / "4.0s"
  796-797, 805, 811-812: late-worker 4.0 / 6.0 / sleep(1.0) / "4.0s" / elapsed < 4.7
  875-876: red _started_late_ _RERUN_TIMEOUT_S 4.0, grace 0.5
  525, 552, 568: the three platform skipifs; 966, 1014: two 2-way parametrizations
tests/test_ad1246_long_run_promotion.py
  26: import pytest   227-229: _beats_code, assert beats <= 50   241: _beats
  476-478: M2 promote 0.6, deadline 1.0   492-494: the fixed-sleep premise   503: beats_at_report < 50
  505-507: the 1.0 s stop check   513-514: 300 s floor
  705-710: _wait_until (asyncio.wait_for around a 0.05 s poll; raises on timeout)
src/probos/cognitive/turn_promotion.py
  187: _ABANDON_GRACE_SECONDS: float = 10.0
  2477: done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)   (rows P1, P2)
  2487-2494: the work item is created after the promotion wait
  2529-2541: reporter = asyncio.create_task(_report_holding_slot(..., deadline_seconds=...))
  2065: supervisor.arm()   (inside _report_holding_slot)
  540-541: _enforce: started = time.monotonic(); asyncio.wait({self._task}, timeout=self._deadline)
  552: self._task.cancel()
  => the BF-733 deadline counts from the promotion, not from the turn's start.
src/probos/config_models/operations.py
  348-350: the BF-733 deadline less a 300 s margin lowers the run clock, never below the 300 s inline clock
src/probos/execution/isolation.py
  712-715: except asyncio.CancelledError: ... request.kill_switch.fire("cancelled")   (row R1)
src/probos/execution/process_tree.py
  171: if _win32().terminate_job(self._job, _KILLED_EXIT_CODE):   (row R2; 1 occurrence)
  193: _kill_direct(self._proc)   (the shell-only fallback R2 falls through to)
src/probos/agents/shell_command.py
  68: DEFAULT_TIMEOUT: float = 30.0   72: WORKER_TEARDOWN_GRACE: float = 5.0
  208: slot.cancel()  # BF-893 ...   (row T3)   214, 288: f"Command timed out after {self.DEFAULT_TIMEOUT}s"
  319: timeout=max(deadline - time.monotonic(), 0.0),   (row T1)
src/probos/agents/red_team.py
  34: _RERUN_TIMEOUT_S = 5.0   35: _RERUN_TEARDOWN_GRACE_S = 5.0
  337, 488: deadline = time.monotonic() + _RERUN_TIMEOUT_S   (read at call time)
  509: stdout_bytes, _ = proc.communicate(timeout=max(deadline - time.monotonic(), 0.0))   (row T2)
src/probos/cognitive/swe_harness/tools.py
  1351: timeout = float(params.get("timeout", 30.0))   1393: f"run_command timed out after {timeout}s"
scripts/gen_ad_ledger.py
  26-31: write mode; --check is what tests/test_ad1184_ad_ledger.py runs
DECISIONS.md:486-497 (BF-913 entry and its validation of record); 497 "Revert the BF-913 commit" (1 occurrence)
PROGRESS.md: "ProbOS Progress" (1 occurrence)
```

**Expected `git diff --stat` for the slice** (test-only):

```
 DECISIONS.md                             | ~12 +
 PROGRESS.md                              |  ~2 +
 docs/development/ad-ledger-snapshot.json |  regenerated
 docs/development/open-ads-report.md      |  regenerated
 tests/test_ad1246_long_run_promotion.py  | ~12 +-
 tests/test_bf893_process_tree.py         | ~60 +-
```

## Absence Verified (2026-11-15)

```
CLAIM: neither test file changed since BF-913's campaign, so its baselines (25 passed 2 skipped; 19 passed) apply
RUN:   git log --oneline cf87c720..HEAD -- tests/test_ad1246_long_run_promotion.py tests/test_bf893_process_tree.py
FOUND: (empty)
HOLDS: yes

CLAIM: no test or fixture imports either module (so no consumer beyond the files themselves and the ledger check)
RUN:   Grep "test_bf893_process_tree|test_ad1246_long_run_promotion" in tests/*.py
FOUND: test_ad1246_long_run_units.py:4 (docstring), test_issue1417_run_python_child_ownership.py:273 (comment)
HOLDS: yes. The only other reference is a JSON fixture, not an import: Grep "test_bf893_process_tree|test_ad1246_long_run_promotion" in tests/fixtures/file_durations.json finds :226 (tests/test_ad1246_long_run_promotion.py, 16.5) only; tests/test_bf893_process_tree.py is unrecorded, so tests/fixtures/duration_scheduler.py:7-10 weights it by its test count times the suite's mean seconds per test. No path changes.

CLAIM: batch 1 does not touch either test file or the tracker anchors used here
RUN:   git diff --stat aee4a43c 27323e47 ; git diff -U1 aee4a43c 27323e47 -- DECISIONS.md PROGRESS.md
FOUND: no test file of this slice; DECISIONS.md hunk at :1805 (before "AD-1346 M3e4d9"); PROGRESS.md hunk after the title line
HOLDS: yes (P3-1 anchors on the title line only; P3-2 anchors at :497-499)

CLAIM: the Windows job is not killed on handle close (so R2's fallback leaves the grandchild alive)
RUN:   Grep "KILL_ON_JOB_CLOSE|terminate_job\(self\._job" src/probos/execution/process_tree.py
FOUND: process_tree.py:171 only
HOLDS: yes
```

## 11. What this does NOT change, and recorded limits

Out of scope:
- product code;
- `scripts/run_test_gate.py` and CI;
- AD-1246 M1 (`:270`, already BF-913's) and M3 (`:603`, which asserts a run still going, not a start);
- the queued-past-the-deadline tests (`:700`, `:819`), which assert that nothing started;
- `test_issue1417_*` (BF-951's, already polled).

- **L1.** Shape B's widening lowers the loss rate, but does not remove the failure mode: a start slower than 7.0 s under load still fails, loudly, as a premise. If it recurs, the next step is a premise-only retry or the Captain's gate rule, not another widening.
- **L2.** R1's margin under the mutant needs the report to land before the child's last beat (about 5.1 s or later). Run the campaign on a quiet host; under heavy load R1 could survive by timing.
- **L3.** M2's poll limit sits 0.5 s inside the deadline, less the store read between the ack and the poll.
- **L4.** The seven tests take about 25 s longer serially in total.
- **L5.** Not run here: the Architect ran no test. The counts are BF-913's, and both files are unchanged since. The probe numbers are the orchestrator's (idle, n=12).

## 12. Prior art and blind spots

This is a test-only bug fix with no outside analogue worth a search; it is ProbOS's own test timing.
- **Internal, absorbed:** BF-913's contract (`prompts/bf-913-child-start-test-budgets.md`, windows derived per mutant) and its rejected list; `test_issue1417_*`'s `wait_for_beats` polling (BF-951).
- **Blind spot, recorded:** the earlier late-worker failure's assertion is unknown. D2 widens both the start window and the report margin so either cause is covered.

## 13. Acceptance criteria

1. Section 8.2's counts on the built tree, and 7 of 7 passed three times serially.
2. Rows T1-T4, P1, P2, R1 and R2 are killed, each by the assertion named (or the one that fired is recorded), on one recorded tree.
3. The diff is exactly the expected `--stat` files; no product file changes.
4. One canonical broad gate with a receipt, before the next batch's gate.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
