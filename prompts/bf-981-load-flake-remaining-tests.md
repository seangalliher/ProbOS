# BF-981 part 2: the rest of the gate-load test family holds under a held child start, a failed listing, a held clock and a held unit end; the gate step names its worker count

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24
**Assembled by:** the orchestrator, 2026-11-24: the section 6 headings and the pair layout follow what `contract_tools.py` reads; the Architect's text is otherwise unchanged.
**Status:** ready to build. **Owning issue:** #1815 (this ends it). It also ticks #1523 F-1 and #1820 bf-885 F1. Commits say `Refs #1815, #1523, #1820.`
**Base:** `542a2a68` (origin/main). **Number:** BF-981 is reused (D6); no AD or BF is allocated.
**Line endings:** the working copies are CRLF and the blocks below are LF; the orchestrator matches them after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 0 new, 0 removed, 6 changed (A1 runs two cases).
**Scope:** test files and docs only. Two instruction files change (`.github/agents/orchestrator.agent.md`, `CLAUDE.md`). No file under `src/` or `scripts/`, and no pytest or CI configuration, changes.

## 1. Problem (premise table)

| Test | Recorded failure | The premise it assumes |
|---|---|---|
| `tests/test_bf893_process_tree.py:941` `test_redteam_outer_timeout_ends_rerun` | `DID NOT RAISE TimeoutError` at `:968` (2026-11-19, 6.61 s); `assert (1991993.718 - 1991989.093) < 4.5` (2026-11-15 gate XML) | Within the re-run's 5 s budget (`:961`) the PowerShell, Python and grandchild chain starts and beats, and the outer 1 s still ends first. When the start uses 4 s or more, the budget's own deadline answers inside the outer second |
| same file, `:1174` `test_in_time_result_unchanged_with_slot` | `'Verification command timed out' == 'Stdout mismatch'` (2026-11-15 gate XML, the third re-run) | Three PowerShell-and-Python runs each finish inside the red team's 5 s (`red_team.py:34`) |
| `tests/test_run_test_gate.py:1873` hard death | `CalledProcessError ... exit status 128`, `failed to read '.git/worktrees/-probos-gate-*/locked': Permission denied` at `:1924` (2026-11-23, 3 workers); `wrapper never entered its materialized preflight` (#1815 body, 16 workers) | Not a start window: `check_output` (`:1924`, `:1947`) treats a transient Windows read failure, which runs concurrently with `git worktree add` (`run_test_gate.py:635`), as fatal (reproduced with git alone, #1815). The second message is a 15 s start premise (`:1922`) |
| `tests/test_ad1246_long_run_promotion.py:877` m5 | `first.error` `'timed out'` (`:927`; 2026-11-08, 11-17, 11-20) and `_wait_until(started.exists, timeout=15)` (`:913`; 2026-11-19); 4 of 83 banked runs | The first child starts and finishes a 2 s sleep inside 3.5 s (`:903`, `:919`), and so holds the slot while the second plans. The 11-19 failure is the same cause: the first child was killed before it wrote `started` |
| `tests/test_ad1246_long_run_units.py:465` (#1523 F-1) | `1000.0000000000146 <= 1000.0` (`:473`) | `(t + 1000.0) - t <= 1000.0` with a live `t` (`:469`; `long_runs.py:113` reads the module's `time`). It fails when `t + 1000.0` falls in a coarser float spacing than `t` |
| `tests/test_bf885_identity_db_units.py:953` A1 (#1820 bf-885 F1) | `IdentityUnitUnsettled: ... the unit has not ended within 0.2 s` from `_end` (`identity_writer.py:158`), hosted Linux CI; the second warning says the unit committed | Every unit of the case ends within the test's 0.2 s (`:41`, `:956`). Only the late unit needs that bound; the refused unit was the re-issued follower's own (`:999`). #1820's text says otherwise and is corrected in section 12 |

The siblings at `test_ad1246_long_run_units.py:161`, `:506` and `:748` stay on the live clock. Their assertions sit at least 113 s from any rounding step: 1187 against 1500 and 1800, and 120 and -50 against 300. `:161` and `:748` check only `reason` and how the note is classified.

## 2. Overview

- **Budgets that are not under test are raised well above any start time.** The red team's budget becomes 30 s in both bf893 tests. The outer-timeout bound becomes 29.0 s, derived against a deadline set after `started_at`.
- **Premises before the timed part are held by construction.**
  - m5: the first run waits for a release file that the second's coroutine writes, so it holds its slot without a fixed sleep. Its budget is 25 s.
  - Hard death: each poll reads through `_worktree_listing`, which returns `None` on a non-zero exit, and the poll treats `None` as "not yet". A failed last poll fails the test by name, so the final check cannot pass on an empty listing. The start premise gets 60 s.
- **A value that is under test keeps its bound; the rest get headroom.** A1 lowers the bound to 0.2 s only around the late unit and restores the production bound once that unit has ended. The W cases keep `_BOUND_S = 0.2`.
- **The clock is held.** F-1 replaces `long_runs.time` with a fixed clock (F-23's precedent, PR #1758) and asserts exactly 1000.0.
- **The gate step names 16 workers.** The rule goes in the orchestrator profile and `CLAUDE.md` points to it.

Rejected, one line each:
- A delay at `Popen` entry: m5's budget starts after `Popen` returns (`isolation.py:889`), so it would not stress m5.
- A retry on an unmet premise: a real regression also fails only sometimes (BF-913's reason).
- Lowering the default worker count: part 1's decision (#1816) still holds.
- A product `now` parameter on `plan_long_run`: this batch is test-only, and holding the module clock reaches the same read.
- Widening the hard-death cleanup's 20 s: that window is the behaviour under test, and no failure of it is recorded.

## 3. Decisions

| # | Decision | Bound derivation |
|---|---|---|
| D1 | Red team outer timeout: budget 30 s (the control too, was 10 s), bound `< 29.0` | The deadline is set after `started_at`, so the budget cannot end the re-run before 30.0 s. The outer timer ends it at P + 1.0 s and the silence check ends by P + 2.0 s, where P is how long the premise took. The mutant that leaves the tree running beats until 30 s, so it is caught whenever P < 28 s; with the probe's 6 s hold, P is about 6.5 s |
| D2 | In-time test: red team budget 30 s | The test checks the answer and the slot's hold and release, not the budget's value; 30 s equals the shell's `DEFAULT_TIMEOUT` (`shell_command.py:68`) |
| D3 | Hard death: `_worktree_listing` with `check=False` returns `None` on failure; start premise 60 s; cleanup window 20 s (unchanged); the final check asserts `listing is not None` | A failed listing never counts as one that shows nothing. 60 + 10 (the wrapper's wait) + 20 stays under the 180 s default timeout (`pyproject.toml:190`) |
| D4 | m5: the first run is held by a release file (child-side limit 20 s), budget 25 s, `max_runtime_seconds` 30.0, outer `wait_for` 60 s | Release comes at most 15 s (the start wait) plus the second run after the gather starts. The second's 1.0 s clock ends it, which leaves it about 9 s of 25 for its own start and kill. 60 s is above 25 plus teardown |
| D5 | F-1: `long_runs.time` held at 5000.0, grant 6000.0, `timeout_seconds == 1000.0` | Both values are exact floats |
| D6 | One number, BF-981 | Each of the six is a test premise that assumed an unloaded host, and each repair is test-only. The hard-death poll is the "different cause" case of #1815's numbering note; it keeps the number because its repair is the same kind |
| D7 | The gate runs at the default of 16 workers | See section 8.5 for the rule if that gate is red |

## 4. Milestones and commits

The Builder applies the pairs only. The orchestrator commits by plumbing. No subject carries an `AD-` or `BF-` token, and no commit text uses the words close, fix or resolve.

- **M1** (S1): P1-1 to P1-6, in `tests/test_bf893_process_tree.py` and `tests/test_run_test_gate.py`. Subject: `Red team re-run, in-time and hard-death gate tests hold under a slow child start and a failed worktree listing`
- **M2** (S2): P2-1 to P2-5, in `tests/test_ad1246_long_run_promotion.py` and `tests/test_ad1246_long_run_units.py`. Subject: `Long-run tests hold the first run's slot by a release file and hold the planner's clock`
- **M3** (S3): P3-1 to P3-5, in `tests/test_bf885_identity_db_units.py`, `.github/agents/orchestrator.agent.md` and `CLAUDE.md`. Subject: `Identity follower test keeps the short bound for the late unit only; the gate step names its worker count`
- **M4** (trackers): P4-1 and P4-2, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`. Subject: `Trackers for the rest of the gate-load test family`

M3 and M4 may be one Builder delegation; each milestone is under about 40 tool calls.

**Risk:** every milestone is Low (test and docs only); none is a shared contract. M3 edits a standing order whose consumer is `tests/test_standing_orders_layout.py`.

**Order and review:** M1, then M2, then M3 and M4. One Diff Reviewer pass covers M1 and M2 (test-only, same family). A second pass covers M3 and M4, and it reads the two doc hunks in full.

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py` (M4), and run `git diff --check` and `git diff --stat`.
- **May not:** run pytest, commit, edit an unnamed file, add `skip`/`xfail`/a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `tests/test_bf893_process_tree.py` (M1)

**P1-1**
SEARCH:
```python
    re-run has 5 s and the outer timer 1 s, started once the heartbeat runs (a slow start cannot fail the premise).
```
REPLACE:
```python
    re-run has 30 s and the outer timer 1 s, started once the heartbeat runs (a slow start cannot fail the premise).
```

**P1-2**
SEARCH:
```python
        # Control: never timed out from outside, the same re-run keeps beating.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control, lambda verdict: verdict.verified is True)

        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 5.0)
        async with _ContendedCall(hold=False, heartbeats=(marker,)) as pool:
            started_at = time.monotonic()
            rerun = pool.submit(
                _rerun(agent, _spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await _heartbeat_is_running(marker, rerun)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(rerun, timeout=1.0)
            assert time.monotonic() - started_at < 4.5, "the re-run's own 5 s budget ended it, not the outer timer"
```
REPLACE:
```python
        # Control: never timed out from outside, the same re-run keeps beating.
        # BF-981: 30 s here and below (were 10 s and 5 s). A gate-loaded start used most of the 5 s, so the re-run's
        # own budget answered inside the outer second ("DID NOT RAISE", #1815).
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 30.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control, lambda verdict: verdict.verified is True)

        # The budget's deadline is set after `started_at`, so it cannot end the re-run before 30.0 s. The outer timer
        # ends it at P + 1.0 s, P being the premise's time, and the silence check ends by P + 2.0 s: a re-run left
        # running (no slot.cancel()) still beats there whenever P < 28 s.
        async with _ContendedCall(hold=False, heartbeats=(marker,)) as pool:
            started_at = time.monotonic()
            rerun = pool.submit(
                _rerun(agent, _spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await _heartbeat_is_running(marker, rerun)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(rerun, timeout=1.0)
            assert time.monotonic() - started_at < 29.0, "the re-run's own 30 s budget ended it, not the outer timer"
```

**P1-3**
SEARCH:
```python
    red_events: list[str] = []
    monkeypatch.setattr("probos.agents.red_team.ProcessTreeSlot", _recording_slot(red_events))
```
REPLACE:
```python
    red_events: list[str] = []
    monkeypatch.setattr("probos.agents.red_team.ProcessTreeSlot", _recording_slot(red_events))
    # BF-981: the shell's 30 s for the re-run too (was 5 s). Under gate load the third PowerShell-and-Python start
    # used the 5 s and answered "Verification command timed out" (#1815); this test checks the answer and the slot.
    monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 30.0)
```

### 6.2 `tests/test_run_test_gate.py` (M1)

**P1-4**
SEARCH:
```python
def test_wrapper_hard_death_cleans_command_worktree_registration_and_lock(
    gate: ModuleType, tmp_path: Path
) -> None:
```
REPLACE:
```python
def _worktree_listing(repo: Path) -> str | None:
    """``git worktree list --porcelain`` in *repo*; None when git could not read it, which a poll treats as not yet.

    BF-981: on Windows a listing that runs while ``git worktree add`` creates a worktree can exit 128 with "failed
    to read .../locked: Permission denied" (reproduced with git alone, #1815). The wrapper's own listing in
    ``_remove_materialized_gate_tree`` reads it with ``check=False`` too.
    """
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo, capture_output=True, text=True, check=False,
    )
    return listed.stdout if listed.returncode == 0 else None


def test_wrapper_hard_death_cleans_command_worktree_registration_and_lock(
    gate: ModuleType, tmp_path: Path
) -> None:
```

**P1-5**
SEARCH:
```python
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            listing = subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo,
                text=True,
            )
            worktrees = [
                Path(line.removeprefix("worktree "))
                for line in listing.splitlines()
```
REPLACE:
```python
        # BF-981: 60 s (was 15 s) for the wrapper to start, materialize its tree and start the phase. This is a premise,
        # and it was among #1815's failures at 16 workers; the cleanup's 20 s below is the behaviour, unchanged.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            listing = _worktree_listing(repo)
            worktrees = [
                Path(line.removeprefix("worktree "))
                for line in (listing or "").splitlines()
```

**P1-6**
SEARCH:
```python
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            listing = subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo,
                text=True,
            )
            if (
                not _process_exists(phase_pid)
                and not gate_root.exists()
                and str(gate_root) not in listing
            ):
                break
            time.sleep(0.1)
        assert not _process_exists(phase_pid)
        assert not gate_root.exists()
        assert str(gate_root) not in listing
```
REPLACE:
```python
        deadline = time.monotonic() + 20
        listing = None
        while time.monotonic() < deadline:
            listing = _worktree_listing(repo)
            if (
                listing is not None
                and not _process_exists(phase_pid)
                and not gate_root.exists()
                and str(gate_root) not in listing
            ):
                break
            time.sleep(0.1)
        assert not _process_exists(phase_pid)
        assert not gate_root.exists()
        assert listing is not None, "the last poll could not list the worktrees, so the registration is unknown"
        assert str(gate_root) not in listing
```

### 6.3 `tests/test_ad1246_long_run_promotion.py` (M2)

**P2-1**
SEARCH:
```python
        # H-4: the validator refuses a 4 s reach, so this config is built without it.
        config=SimpleNamespace(execution=ExecutionConfig.model_construct(
            enabled=True, scratch_dir=str(tmp_path / "scratch"), max_runtime_seconds=4.0,
```
REPLACE:
```python
        # H-4: the validator refuses a 30 s reach, so this config is built without it.
        config=SimpleNamespace(execution=ExecutionConfig.model_construct(
            enabled=True, scratch_dir=str(tmp_path / "scratch"), max_runtime_seconds=30.0,
```

**P2-2**
SEARCH:
```python
    started = tmp_path / "first-started.txt"
    first_code = (
        f"import pathlib, time\npathlib.Path({str(started)!r}).write_text('up')\n"
        "time.sleep(2)\nprint('first done')\n"
    )
```
REPLACE:
```python
    started = tmp_path / "first-started.txt"
    release = tmp_path / "first-release.txt"
    # BF-981: the first run holds its slot until the second has run (the release file), not for a fixed 2 s sleep
    # inside a 3.5 s budget, whose 1.5 s margin a gate-loaded start used (#1815). Its 25 s budget: the release comes
    # at most 15 s (the start wait below) plus the second run (its 1.0 s clock, then its kill) after the gather
    # starts. The child's own 20 s limit only ends a run the release never reached.
    first_code = (
        f"import pathlib, time\npathlib.Path({str(started)!r}).write_text('up')\n"
        "end = time.monotonic() + 20\n"
        f"while not pathlib.Path({str(release)!r}).exists() and time.monotonic() < end:\n"
        "    time.sleep(0.05)\n"
        "print('first done')\n"
    )
```

**P2-3**
SEARCH:
```python
    async def _second_once_the_first_holds_the_slot() -> ToolResult:
        await _wait_until(started.exists, timeout=15)
        return await tool.invoke({"code": second_code, "timeout": 3.5}, context)

    try:
        first, second = await asyncio.wait_for(
            asyncio.gather(
                tool.invoke({"code": first_code, "timeout": 3.5}, context),
                _second_once_the_first_holds_the_slot(),
            ),
            timeout=30,
        )
```
REPLACE:
```python
    async def _second_once_the_first_holds_the_slot() -> ToolResult:
        try:
            await _wait_until(started.exists, timeout=15)
            return await tool.invoke({"code": second_code, "timeout": 3.5}, context)
        finally:
            release.write_text("go", encoding="utf-8")  # the first run ends once the second has run, however it ended

    try:
        first, second = await asyncio.wait_for(
            asyncio.gather(
                tool.invoke({"code": first_code, "timeout": 25.0}, context),
                _second_once_the_first_holds_the_slot(),
            ),
            timeout=60,
        )
```

**P2-4**
SEARCH:
```python
        ) == [(1.0, False, True), (3.5, True, False)]
```
REPLACE:
```python
        ) == [(1.0, False, True), (25.0, True, False)]
```

### 6.4 `tests/test_ad1246_long_run_units.py` (M2)

**P2-5**
SEARCH:
```python
async def test_plan_long_run_turn_time_left_lowers_the_request() -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        plan = _plan(service, 1500.0, grant=LongRunGrant(time.monotonic() + 1000.0))
        assert plan is not None and plan.ticket is not None
        tickets.append(plan.ticket)
        # The turn's time left binds, below both the request and max_runtime_seconds.
        assert 900.0 < plan.timeout_seconds <= 1000.0
```
REPLACE:
```python
async def test_plan_long_run_turn_time_left_lowers_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # BF-981 (#1523 F-1): the planner's clock is held. With a live clock `(t + 1000.0) - t` exceeded 1000.0 by one
    # rounding step when t + 1000.0 fell in a coarser float spacing than t, and `<= 1000.0` failed. Both values here
    # are exact, so the time left is 1000.0 and is asserted exactly. The module attribute is replaced, never
    # time.monotonic itself, which the event loop reads.
    monkeypatch.setattr(long_runs, "time", SimpleNamespace(monotonic=lambda: 5000.0))
    service = LongRunService()
    tickets: list[Any] = []
    try:
        plan = _plan(service, 1500.0, grant=LongRunGrant(5000.0 + 1000.0))
        assert plan is not None and plan.ticket is not None
        tickets.append(plan.ticket)
        # The turn's time left binds, below both the request and max_runtime_seconds.
        assert plan.timeout_seconds == 1000.0
```

### 6.5 `tests/test_bf885_identity_db_units.py` (M3)

**P3-1** (A1 no longer lowers the bound at its start)
SEARCH:
```python
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    store = _GatedSignStore(KeyringKeyStore(backend=duck))
```
REPLACE:
```python
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    store = _GatedSignStore(KeyringKeyStore(backend=duck))
```

**P3-2**
SEARCH:
```python
        shared.fail_held = True  # the late unit's COMMIT, once released, fails: its unit is rolled back
        try:
            late = asyncio.create_task(_birth(registry, "Worf"))
```
REPLACE:
```python
        shared.fail_held = True  # the late unit's COMMIT, once released, fails: its unit is rolled back
        # BF-981 (#1820 bf-885 F1): the 0.2 s bound is for the late unit only, which this case refuses at the bound.
        # Troi's birth before it and every unit after it has ended (the re-issued follower, the peer's import, the
        # restart) check where a block lands, so they run at the production bound. At 0.2 s a loaded runner refused
        # the re-issued follower's own unit, which then committed (the CI run of PR #1826).
        production_bound = identity_writer.IDENTITY_UNIT_SETTLE_S
        monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
        try:
            late = asyncio.create_task(_birth(registry, "Worf"))
```

**P3-3**
SEARCH:
```python
            gate.set()
            await asyncio.wait({_ending(registry)}, timeout=5)  # the late unit's COMMIT failed; it was rolled back
            signing.set()
```
REPLACE:
```python
            gate.set()
            await asyncio.wait({_ending(registry)}, timeout=5)  # the late unit's COMMIT failed; it was rolled back
            monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", production_bound)  # the late unit has ended
            signing.set()
```

### 6.6 `.github/agents/orchestrator.agent.md` (M3), written for the case where the gate at 16 is green

**P3-4** (a new last bullet of **Gate, Batch and Push**, outside the Size findings paragraph at `:48`)
SEARCH:
```markdown
## Session Log Trim (Standing Order)
```
REPLACE:
```markdown
- **Gate workers (BF-981, #1815).** Run the broad gate at the wrapper's default of 16 workers (`--workers` in `scripts/run_test_gate.py`). A test that fails only at that count is triaged as a defect of that test, the way BF-981 treated its family, not answered with a lower count. A lower count is a diagnostic run, or needs a measured reason recorded in the gate report and the owning issue.

## Session Log Trim (Standing Order)
```

### 6.7 `CLAUDE.md` (M3)

**P3-5** (step 5 points to the rule; the indented line continues step 5)
SEARCH:
```markdown
6. **Push and verify closure** only after a green gate: one PR for the batch, then every issue or parent checklist it closes.
```
REPLACE:
```markdown
   Its worker count: **Gate workers** in `.github/agents/orchestrator.agent.md`.
6. **Push and verify closure** only after a green gate: one PR for the batch, then every issue or parent checklist it closes.
```

### 6.8 Contingency text, applied by hand under section 8.5 row 3 only (not a pair for the tool)

**P3-4-ALT (only under section 8.5, row 3).** Replace the new bullet's text with the following, fill the placeholder, and re-gate at 3 workers:
`- **Gate workers (BF-981, #1815).** Run the broad gate with `--workers 3`; the default in `scripts/run_test_gate.py` is 16. At 16 the canonical gate of BF-981 part 2 failed twice on <ORCHESTRATOR: the failing tests, all outside this family, with each gate's label and counts>, so 3 is the count the gate step expects until a gate at 16 is green on an unchanged tree.`
P3-5 stays as written.

### 6.9 `PROGRESS.md` (M4)

**P4-1**
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-981 part 2 (2026-11-24), #1815 -- the rest of the gate-load test family holds under a held child start, a failed listing, a held clock and a held unit end.** Test and docs only. `tests/test_bf893_process_tree.py`: the red team's outer-timeout test and the in-time test give the re-run 30 s (were 5 s; the control 30 s, was 10 s), and the outer-timeout bound is 29.0 s (was 4.5 s). `tests/test_run_test_gate.py`: the hard-death test reads `git worktree list` through `_worktree_listing`, which returns None on a non-zero exit, so a transient Windows read failure is a poll that has not seen it yet; a failed last poll fails the test; the wrapper's start premise has 60 s (was 15 s). `tests/test_ad1246_long_run_promotion.py`: M5's first run holds its slot until the second has run (a release file), with a 25 s budget (was a 2 s sleep inside 3.5 s). `tests/test_ad1246_long_run_units.py` (#1523 F-1): the planner's clock is held and the time left is asserted as exactly 1000.0. `tests/test_bf885_identity_db_units.py` (#1820 bf-885 F1): A1 keeps the 0.2 s bound for the late unit only; every other unit runs at the production bound. `.github/agents/orchestrator.agent.md` names the gate's worker count (16, the default) and `CLAUDE.md` step 5 points to it. Effect, measured with a stressor kept outside the repository: on the base, rows L1 to L4, L6 and L7 fail at an assertion of the test (L1 at the grandchild-start premise; L2 at `agreed.verified is True`; L3 waiting for the first run's start file; L4 with `CalledProcessError` at the first poll; L6 with `IdentityUnitUnsettled` in both cases; L7 at `1000.0000000002328 <= 1000.0`) and the candidate passes them; L5 fails on the base with `CalledProcessError` and on the candidate at the last-poll assertion. Six tests change (A1 has two cases); none is added. Contract `prompts/bf-981-load-flake-remaining-tests.md`.
```
The first 120 characters hold no ledger status word (`gen_ad_ledger.py:126-139`).

### 6.10 `DECISIONS.md` (M4)

**P4-2** (after the part-1 entry)
SEARCH:
```markdown
- *Reversal.* Revert the BF-981 commits. Nothing persisted changes.
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-981 commits. Nothing persisted changes.

### BF-981 part 2 -- The rest of the gate-load test family holds under a held start, listing, clock and unit end; the gate runs at 16 workers (2026-11-24, #1815)

- *Scope.* Six tests: `tests/test_bf893_process_tree.py` (red team outer timeout, in-time result), `tests/test_run_test_gate.py` (hard death), `tests/test_ad1246_long_run_promotion.py` (M5), `tests/test_ad1246_long_run_units.py` (turn time left, #1523 F-1) and `tests/test_bf885_identity_db_units.py` (A1, #1820 bf-885 F1). Also `.github/agents/orchestrator.agent.md` and `CLAUDE.md`. Contract: `prompts/bf-981-load-flake-remaining-tests.md`.
- *Causes (from the recorded failures; none implicates product code).*
  - A gate-loaded child start used a fixed budget: the red team's 5 s, and M5's 1.5 s margin (4 of 83 banked runs).
  - The hard-death poll treated a transient `git worktree list` read failure (exit 128, reproduced with git alone) as fatal.
  - The turn-time test compared a live float difference to 1000.0 at its edge.
  - A1 ran a follower's own unit at the 0.2 s test bound.
- *D1.* A budget that is not under test is raised far above the start (red team 30 s). A premise before the timed part is held by construction (M5's release file; the listing poll's "not yet", whose failed last poll fails the test). A bound under test keeps its value (A1's late unit at 0.2 s).
- *D2.* The outer-timeout bound is 29.0 s against a 30 s budget whose deadline is set after the clock starts.
- *D3.* The gate step expects the default, 16 workers.
- *Numbering.* One number for the six: each is a test premise that assumed an unloaded host, and each repair is test-only. The hard-death poll is the case that #1815's note reserved for a new number; it keeps BF-981 because its repair is of the same kind.
- *Proof method.* A stressor kept outside the repository: a direct child held suspended for 6.0 s after it is created; failed listings; a held clock where `(t + 1000.0) - t > 1000.0`; a 0.5 s hold of each unit end after the late unit. Each production mutant is killed on the candidate wherever it is killed on the base, quiet and under the stressor. Effect: on the base every row fails (L1 at the grandchild-start premise, L2 at `agreed.verified is True`, L3 waiting for the first run's start file, L4 and L5 with `CalledProcessError`, L6 with `IdentityUnitUnsettled` in both cases, L7 at `1000.0000000002328 <= 1000.0`); on the candidate L1 to L4, L6 and L7 pass and L5 fails at the last-poll assertion. The mutants RT1, RT2, H1, M5a, F1a and B1 are killed on the base and on the candidate, quiet and under the stressor; M5c survives the M5 case on both and is killed by the plan-level cases of `tests/test_ad1246_long_run_units.py`.
- *Rejected.* A delay at `Popen` entry (M5's budget starts after `Popen` returns); a retry on an unmet premise; lowering the default worker count; a product `now` parameter for `plan_long_run`.
- *Reversal.* Revert the part-2 commits. Nothing persisted changes.
```

## 7. Consumers

| Consumer | What it reads | Status |
|---|---|---|
| `tests/test_ad1198_transfer_recheck.py:173` | imports `_rows` and `_SharedFactory` from the bf885 file | both are unchanged |
| `tests/test_issue1417_run_python_child_ownership.py:196`, `:273` | comments saying helpers were copied from the ad1246 files | no import and no text pin |
| `tests/test_ad1246_long_run_units.py:4` | names the promotion file in its docstring | no pin |
| `tests/fixtures/duration_scheduler.py:29` | names `test_run_test_gate.py` in a docstring | no path changes |
| `tests/test_standing_orders_layout.py` | duplicates across files (`:380`; this counts within one file too, `:236-242`); pointer paths exist (`:606`); `PROCEDURE` stays in O (`:101-129`, `:455`); Size findings paragraph and its 7 sentences (`:555-600`) | the new sentences are unique; both backticked paths exist; no needle moves; the bullet is under `:134`, and the paragraph is at `:48` |
| `tests/test_bf943_captain_document_write_refusal.py:36` | `CLAUDE.md` as a real file | does not depend on its content |
| `tests/test_ad1184_ad_ledger.py` | `gen_ad_ledger.py --check` | M4 regenerates the ledger |

Not checked: other readers of `CLAUDE.md` or the orchestrator profile outside `tests/` and `scripts/` (for example the Copilot runtime), which no test pins.

## 8. Gates (the orchestrator runs all of them)

### 8.1 On the oracle tree, before the Builder starts

| # | Check | Expected |
|---|---|---|
| O1 | Every SEARCH in section 6, LF-normalised, counted in its file at its turn | 1 each |
| O2 | `rg -n "_worktree_listing\|production_bound" tests` | no match, except `tests/test_ward_room_identity_keys.py:363` (a test name in another file, found on 542a2a68) |
| O3 | `rg -n -e "--workers" -e "Gate workers" .github/agents/orchestrator.agent.md CLAUDE.md` | no match |
| O4 | Base counts: the focused command of 8.2 at `-n 0 -p no:randomly` | record them; the candidate must match |
| O5 | Rows L1-L7 of 8.3 on the base | each fails at an assertion of the test (not an error of the probe), and the probe log shows its expected event. L5 fails on the base too (`CalledProcessError`) |
| O6 | Every mutation row of 8.4 on the base, quiet host | record KILLED or SURVIVED: this is the parity reference |

### 8.2 Focused check on the candidate

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf893_process_tree.py tests/test_run_test_gate.py tests/test_ad1246_long_run_promotion.py tests/test_ad1246_long_run_units.py tests/test_bf885_identity_db_units.py tests/test_ad1198_transfer_recheck.py tests/test_standing_orders_layout.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
```
Expected: the O4 counts, all passed. Then run the six changed tests three times serially on a quiet host: 7 passed each time.

### 8.3 Stressor rows (`-n 0 -p no:randomly`, win32)

The probe lives outside the repository, at `%TEMP%\bf981-probe\bf981_probe.py`. Run each row with `PYTHONPATH=<that dir>` and `-p bf981_probe`, and set `BF981_PROBE`, `BF981_PROBE_LOG` (a fresh path for each row) and `BF981_PROBE_HOLD_S`. When its expected event is missing, the probe exits the session with status 3 and prints `BF981 PROBE NOT APPLIED`; such a row is INVALID.

```python
"""BF-981 part 2 stressor; not part of the repository. win32 only. Modes: hold, gitlist_alternate,
gitlist_after_kill, clock, identity_hold."""
import asyncio, ctypes, json, os, subprocess, sys, threading, time
from ctypes import wintypes
from types import SimpleNamespace

MODE, LOG = os.environ["BF981_PROBE"], os.environ["BF981_PROBE_LOG"]
HOLD_S = float(os.environ.get("BF981_PROBE_HOLD_S", "0"))
EXPECT = {"hold": "suspend", "gitlist_alternate": "gitlist_fail", "gitlist_after_kill": "gitlist_fail",
          "clock": "clock", "identity_hold": "end_held"}[MODE]
LIST = ["git", "worktree", "list", "--porcelain"]
FAIL = [sys.executable, "-c", "import sys; sys.stderr.write('fatal: failed to read worktrees/x/locked: "
        "Permission denied\\n'); sys.exit(128)"]
state = {"lists": 0, "killed": False, "armed": False, "patched": False}

def log(**row):
    with open(LOG, "a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")

k32, nt = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("ntdll")
k32.OpenProcess.restype, k32.OpenProcess.argtypes = wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
k32.CloseHandle.argtypes = (wintypes.HANDLE,)
for fn in (nt.NtSuspendProcess, nt.NtResumeProcess):
    fn.restype, fn.argtypes = ctypes.c_long, (wintypes.HANDLE,)

def hold(pid, argv0):
    handle = k32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    ok = bool(handle) and nt.NtSuspendProcess(handle) == 0
    log(event="suspend", pid=pid, argv0=argv0, ok=ok, t=time.monotonic())
    if handle:
        def resume():
            status = nt.NtResumeProcess(handle); k32.CloseHandle(handle)
            log(event="resume", pid=pid, status=status, t=time.monotonic())
        threading.Timer(HOLD_S, resume).start()  # not a daemon: a held child is always resumed

real_init, real_kill = subprocess.Popen.__init__, subprocess.Popen.kill

def init(self, args, *a, **kw):
    if MODE.startswith("gitlist") and isinstance(args, list) and args == LIST:
        state["lists"] += 1
        if state["killed"] if MODE == "gitlist_after_kill" else state["lists"] % 2 == 1:
            log(event="gitlist_fail", n=state["lists"]); args = FAIL
    real_init(self, args, *a, **kw)
    if MODE == "hold" and isinstance(args, list) and \
            os.path.basename(str(args[0])).lower().startswith(("python", "powershell")):
        hold(self.pid, str(args[0]))

def kill(self):
    if MODE == "gitlist_after_kill" and "hard_death_gate" in str(self.args):
        state["killed"] = True; log(event="wrapper_killed")
    return real_kill(self)

if MODE in ("hold", "gitlist_alternate", "gitlist_after_kill"):
    subprocess.Popen.__init__, subprocess.Popen.kill = init, kill

def pytest_runtest_setup(item):
    if state["patched"]:
        return
    if MODE == "clock":
        t = 2.0 ** 21 - 1000.0
        while (t + 1000.0) - t <= 1000.0 and t < 2.0 ** 21 - 900.0:
            t += 0.0001
        assert (t + 1000.0) - t > 1000.0, "probe premise: no clock value rounds the grant up"
        clock = SimpleNamespace(monotonic=lambda: t)
        item.module.time = clock; sys.modules["probos.execution.long_runs"].time = clock
        state["patched"] = True; log(event="clock", t=t, excess=(t + 1000.0) - t - 1000.0)
    elif MODE == "identity_hold":
        writer = sys.modules["probos.identity_writer"].IdentityWriter
        real_ended = writer._ended
        async def ended(self, db, commit, committed):
            if state["armed"]:
                log(event="end_held", t=time.monotonic()); await asyncio.sleep(HOLD_S)
            try:
                failure = await real_ended(self, db, commit, committed)
            except BaseException:
                state["armed"] = True; log(event="armed"); raise
            if failure is not None and not state["armed"]:
                state["armed"] = True; log(event="armed")
            return failure
        writer._ended = ended; state["patched"] = True

def pytest_sessionfinish(session, exitstatus):
    rows = [json.loads(line) for line in open(LOG, encoding="utf-8")] if os.path.exists(LOG) else []
    if not any(r["event"] == EXPECT and r.get("ok", True) for r in rows):
        sys.stderr.write(f"BF981 PROBE NOT APPLIED ({MODE})\n"); session.exitstatus = 3
```

| Row | Mode, hold | Selector | Base (old text) | Candidate |
|---|---|---|---|---|
| L1 | `hold`, 6.0 | `test_bf893_process_tree.py::test_redteam_outer_timeout_ends_rerun` | fails at a test assertion (the budget ends while the child is held) | passes; at least 2 `suspend` rows with `ok: true` |
| L2 | `hold`, 6.0 | `...::test_in_time_result_unchanged_with_slot` | fails at `agreed.verified is True` or a later red-team check | passes; at least 3 `suspend` rows |
| L3 | `hold`, 6.0 | `test_ad1246_long_run_promotion.py::test_m5_second_long_run_gets_the_inline_clock_when_slots_are_full` | fails (`_wait_until` TimeoutError or `first.error is None`) | passes; at least 2 `suspend` rows |
| L4 | `gitlist_alternate` | `test_run_test_gate.py::test_wrapper_hard_death_cleans_command_worktree_registration_and_lock` | fails with `CalledProcessError` | passes; at least 2 `gitlist_fail` rows |
| L5 | `gitlist_after_kill` | same as L4 | fails with `CalledProcessError` | **fails** at `the last poll could not list the worktrees`; this proves the final check is not vacuous |
| L6 | `identity_hold`, 0.5 | `test_bf885_identity_db_units.py::test_bf885_a1_a_follower_of_a_unit_that_failed_late_is_anchored_where_it_lands_and_verifies_remotely` (both cases) | both cases fail (`IdentityUnitUnsettled`) | both pass; the first `armed` row comes before any `end_held` row |
| L7 | `clock` | `test_ad1246_long_run_units.py::test_plan_long_run_turn_time_left_lowers_the_request` | fails at `900.0 < plan.timeout_seconds <= 1000.0` | passes |

### 8.4 Mutation rows (one row at a time, restored before the next)

Each row runs on the base (quiet host, already done in O6) and on the candidate twice: quiet, and under its slice's stressor row where the table names one.

**Rule:** the candidate must be KILLED in both runs wherever the base is KILLED. A row the base survives is recorded and reported to the Architect, and it does not stop the slice. A candidate survivor where the base was killed stops the slice for triage.

This is the campaign of record. Record the tree id and the sha256 of each mutated file and each changed test file; a rerun on identical hashes repeats nothing.

| Row | File:line on `542a2a68` | Original (stripped) | Mutant | Selector | Stressor | Expected killer |
|---|---|---|---|---|---|---|
| RT1 | `src/probos/agents/red_team.py:348` | `slot.cancel()  # BF-893: an enclosing timeout must not leave the re-run's tree running` | `pass` | outer-timeout test | L1 | `a descendant was still beating after the call ended` |
| RT2 | `src/probos/agents/red_team.py:516` | `slot.release()  # before close(): cancel() never sees a closed job` | `slot.cancel()` | in-time test | L2 | `assert red_events == ["hold", "release"]` |
| H1 | `scripts/_gate_process_supervisor.py:153` | `if _cleanup_worktree(repo_root, gate_root):` | `if True:` | hard death | L4 | `assert not gate_root.exists()` |
| M5a | `src/probos/execution/long_runs.py:410` | `return LongRunPlan(ceiling, None, _wall_clock(wanted, ceiling, "long_runs_busy"))` | `return None` | m5 | L3 | the `second.output["wall_clock"]` check (a KeyError) |
| M5c | `src/probos/execution/long_runs.py:413` | `if applied >= wanted:` | `if False:` | m5 | L3 | `assert "wall_clock" not in first.output` |
| F1a | `src/probos/execution/long_runs.py:412` | `applied = max(ceiling, min(wanted, max_runtime, remaining))` | `applied = max(ceiling, min(wanted, max_runtime))` | F-1 test | -- | the timeout assertion (it gets 1500.0) |
| B1 | `src/probos/identity.py:963` and `:967` | `signed = None` / `signed = await self._key_binding.sign_record_locked(vc)` | `signed = await self._key_binding.sign_record_locked(vc) if self._key_binding is not None else None` / `pass` | A1 `[birth]` | L6 | `_anchor(block["attestation"]["jws"]) == block["index"]`: signing before admission anchors on the late unit's pending tip (`identity_key_binding.py:364`) |

### 8.5 Broad gate and the worker value

Run one canonical gate on the frozen batch at the default of 16 workers: `scripts/run_test_gate.py --label <label> --receipt logs/gates/<label>.receipt.json`.

| # | Outcome | Action |
|---|---|---|
| 1 | Green | P3-4 stands; the batch is done |
| 2 | Red on a changed test or another test #1815 lists | Stop. Architect triage: the repair did not hold under load. No doc change |
| 3 | Red only outside the family | Rerun once at 16 on the unchanged head. If green, P3-4 stands. If red again, apply P3-4-ALT, commit, and re-gate at `--workers 3`; record both red gates on #1815 |

## 9. Diff Reviewer: properties to verify

1. The diff touches only the 5 test files, the 2 instruction files, `PROGRESS.md`, `DECISIONS.md` and the 2 regenerated ledger files.
2. Each derived inequality holds:
   - the outer-timeout bound is under the budget (29.0 < 30.0), and the budget's deadline is computed after `started_at` (`red_team.py:337`);
   - m5's first-run budget (25.0) is at most `max_runtime_seconds` (30.0), and the outer `wait_for` (60) exceeds the budget;
   - the hard-death windows plus the wrapper's wait stay under 180 s.
3. No premise becomes vacuous:
   - a `None` listing never passes the final check;
   - `active_at_admit == [0, 1]` and every A1 premise assertion remain;
   - A1 lowers the bound before the late task starts and restores it only after awaiting the late unit's end;
   - the F-1 assertion is strictly stronger.
4. No `skip`, `xfail`, retry or broadened `except` is added. `check=False` appears only in `_worktree_listing`.
5. `_BOUND_S`, `_rows` and `_SharedFactory` are unchanged, and the W cases still lower the bound to `_BOUND_S`.
6. `long_runs.time` is replaced as a module attribute; `time.monotonic` is never patched globally.
7. The worker rule has one owner, the orchestrator profile, and `CLAUDE.md` only points to it. The new sentences are unique, they sit outside the Size findings paragraph, and the files stay ASCII.
8. Comments state measured causes as measured and cite no line numbers. The tracker text matches the diff, and no ledger status word appears within the first 120 characters of the `PROGRESS.md` head.

## 10. Verified Against Codebase (2026-11-24, tree `542a2a68`)

```
tests/test_bf893_process_tree.py: 941 def test_redteam_outer_timeout_ends_rerun; 948 "re-run has 5 s"; 954-955 control + 10.0
  (10.0 also at 844, 878: P1-2 anchors on the comment at 954); 961 5.0 (only); 963 started_at; 968-970;
  1174 in-time test; 1195-1196 red_events / ProcessTreeSlot (only); 365-372 _heartbeat_is_running (20 s polls)
src/probos/agents/red_team.py: 34 _RERUN_TIMEOUT_S = 5.0; 337 deadline at call time; 340-349 wait_for, 348 slot.cancel();
  488-490 deadline check before Popen; 494 Popen; 509 communicate; 516 slot.release()
src/probos/agents/shell_command.py: 68 DEFAULT_TIMEOUT: float = 30.0
tests/test_run_test_gate.py: 11 import subprocess; 1873 test; 1922 + 15; 1924, 1947 check_output; 1945 + 20; 1959-1961
scripts/run_test_gate.py: 534-545 listing check=False; 562-593 janitor (--cleanup-watch); 635 worktree add; 1763 --workers default=16
scripts/_gate_process_supervisor.py: 96-116 _cleanup_worktree; 151-155 the 30 s cleanup loop, 153 the H1 line
tests/test_ad1246_long_run_promotion.py: 713-718 _wait_until; 877 m5; 891-893 H-4 + 4.0; 900-904; 912-923; 927; 942 (only)
src/probos/tools/code_execution_tool.py: 724-740 plan replaces timeout; 745-750 track_inline_run
src/probos/execution/isolation.py: 862 Popen; 889 communicate(timeout=request.timeout_seconds), after Popen
src/probos/execution/process_tree.py: 10, 38, 64 CREATE_SUSPENDED; 94-102 NtResumeProcess (suspend counts stack with the probe)
src/probos/execution/long_runs.py: 36 import time; 109-113 remaining() reads module time; 404 wanted <= ceiling -> None;
  409-416 the busy, applied and reason lines
tests/test_ad1246_long_run_units.py: 17 import time; 19 SimpleNamespace; 23 pytest; 29 long_runs; 161, 506, 748 siblings; 465-473
src/probos/identity_writer.py: 37 IDENTITY_UNIT_SETTLE_S = 6.0; 115-133 _admitted (A-1 at 119-122); 135-165 _end
  (141 deadline, 158 the raise); 137 self._ended(db, commit, committed)
src/probos/identity.py: 962-967 ledger lock, unit, sign inside it; identity_key_binding.py:364 anchor = _ledger_tip(db) + 1
tests/test_bf885_identity_db_units.py: 41 _BOUND_S; 715 W2 reads the production bound first (precedent);
  956-959 (959 only); 976-978 (978 only); 988-990 (989 only); 999 the re-issue
.github/agents/orchestrator.agent.md: 48 Size findings marker; 129 Gate, Batch and Push; 134 gate command bullet;
  136 "## Session Log Trim (Standing Order)" (once)
CLAUDE.md: 23 step 5; 24 step 6 (once)
tests/test_standing_orders_layout.py: 101-129 PROCEDURE; 146 _POINTER; 223-242 sentence units and duplicates; 380; 455; 500-600
DECISIONS.md: 507 "Revert the BF-981 commits" (once). PROGRESS.md: "ProbOS Progress" (count 1)
scripts/gen_ad_ledger.py: 113 _TOKEN_RE; 126-139 status words, 120-character head window
pyproject.toml: 190 timeout = 180; 196 addopts "-n 16 --dist=loadfile"
```

## Absence Verified (2026-11-24)

```
CLAIM: the new names do not exist yet
RUN:   Grep "_worktree_listing|production_bound" tests/
FOUND: tests/test_ward_room_identity_keys.py:363 (production_bound inside a function name, another file)
HOLDS: yes

CLAIM: no worker count is documented in either instruction file
RUN:   Grep "workers" CLAUDE.md; Grep "workers" .github/agents/orchestrator.agent.md
FOUND: none in CLAUDE.md; in the orchestrator profile only "--workers" is absent (the earlier session verified it)
HOLDS: yes

CLAIM: no test imports or pins the text of the edited test files, except the ad1198 import
RUN:   Grep "test_ad1246_long_run|test_bf893_process_tree|test_bf885_identity_db_units|test_run_test_gate" tests/*.py
FOUND: duration_scheduler.py:29 (docstring), test_ad1198_transfer_recheck.py:173 (import _rows, _SharedFactory),
       test_ad1246_long_run_units.py:4, test_ad1270e1_config_facade.py:1817, test_ad1299_s1a_repair_candidate.py:80,141,
       test_issue1417_run_python_child_ownership.py:196,273 (comments)
HOLDS: yes

CLAIM: long_runs reads `time` only in LongRunGrant.remaining
RUN:   Grep "\btime\b" src/probos/execution/long_runs.py
FOUND: 36 (import), 113 (remaining), 356 and 387 (prose)
HOLDS: yes

CLAIM: the edited files changed since #1816 only by ab723743 (M0 of #1796), which this contract's anchors already include
RUN:   git log --oneline 79986971..HEAD -- <the 5 test files> CLAUDE.md .github/agents/orchestrator.agent.md
FOUND: ab723743
HOLDS: yes (the anchors were read on 542a2a68)

CLAIM: psutil is not available to the probe, so it uses ntdll directly
RUN:   Glob psutil* in d:/ProbOS/.venv/Lib/site-packages; Grep psutil pyproject.toml
FOUND: none
HOLDS: yes
```

## 11. What this does NOT change, and recorded limits

- Product code, `scripts/`, CI, the worker default, BF-981 part 1's seven tests, and `test_run_test_gate.py:1480` (it lists after the run, with no concurrent add).
- **L1.** The stressor holds only direct children. A slow grandchild (the bf893 beater) is covered by the premise polls and is not reproduced.
- **L2.** The suspension follows `CreateProcess` by a few milliseconds, so a child can run briefly before it is held. Python reaches user code later than that; this was not measured.
- **L3.** Not measured: the loss rate at 16 workers over later gates, the hosted Linux runner (CI only), and whether part 1's tests still fail at 16.
- **L4.** A2 (`:1016`) and A3 (`:1071`) still lower the bound for their whole test (filed as item bf-981 L1).
- **L5.** The Architect ran no test. Every count and row is the orchestrator's to measure.

## 12. Issue texts

**#1815, comment that ends the issue:**
"BF-981 part 2 (PR #<n>, merge `<sha>`) ends this issue. Its acceptance was Option 1 or 2, plus documenting the worker count the gate step expects.
- Option 1, test by test, each with a stressor row in which the old text fails and the new one passes (contract section 8.3):
  - `test_redteam_outer_timeout_ends_rerun`: a 30 s budget, L1.
  - `test_in_time_result_unchanged_with_slot`: L2.
  - `test_m5_...`: a release file, L3.
  - Hard death: `_worktree_listing`, L4; L5 shows that its final check fails on a failed last poll.
- The production mutants RT1, RT2, H1, M5a and M5c are killed on the candidate wherever they are killed on the base, quiet and under the stressor: <results>.
- The worker count: **Gate workers** in `.github/agents/orchestrator.agent.md` names 16, the default, and `CLAUDE.md` step 5 points to it. The batch's canonical gate at 16: <label, counts, receipt>.
- Numbering: the hard-death poll's cause (a transient git read) is not a start-window premise. It keeps BF-981 because its repair is test-only like the rest (DECISIONS, BF-981 part 2, *Numbering*).
- Not measured: the rate at 16 workers over later gates, and Linux."

**#1523 F-1:** in the body, change `- [ ] **F-1 (Medium)` to `- [x]` and append to the item:
" **Repaired (BF-981 part 2, PR #<n>, merge `<sha>`), evidence <date>:** the test holds `long_runs`' clock (F-23's pattern) and asserts the time left as exactly 1000.0. With the clock held where `(t + 1000.0) - t > 1000.0`, the old test fails and the new one passes (row L7), and mutant F1a is killed. The siblings at `:161`, `:506` and `:748` stay on the live clock: their assertions sit at least 113 s from any rounding step."
Then post a one-line comment on #1523 that links the tick. An aggregator item is ticked by the body checkbox plus this dated evidence sentence in the item; the evidence is the stressor row and the mutation row.

**#1820 bf-885 F1:** tick the checkbox and append:
" **Repaired (BF-981 part 2, PR #<n>, merge `<sha>`), evidence <date>:** A1 keeps the 0.2 s bound for the late unit only. Troi's birth and every unit after the late unit has ended run at the production bound, read before the test lowers it. Correction to the evidence above: the refused unit was the re-issued follower's own. The traceback ends in `_end` (`identity_writer.py:158`), not in the A-1 admission check (`:120`), and the second warning says that unit committed. With every unit end after the late one held 0.5 s, the old A1 fails both cases and the new one passes both (row L6); mutant B1: <result>. The cases that check the bound fires still use `_BOUND_S = 0.2`."

**New items for #1820** (no new issue):
- **bf-981 L1** (P3, Low; test-only; reach: a loaded runner; no occurrence recorded, banked runs not scanned): A2 (`tests/test_bf885_identity_db_units.py:1016`) and A3 (`:1071`) lower the bound to 0.2 s for the whole test, so their units after the late one have A1's old exposure. Smallest repair: A1's pattern.
- **bf-981 L2** (P3, docs drift): the gate bullet's "roughly 15-19 minutes" (`.github/agents/orchestrator.agent.md:134`) does not match #1815's measurements: 30 and 44 min at 16 workers, and 1 h 13 min at 3.

## 13. Prior art and blind spots

This is test triage, so the external search was skipped, per Prior Art and Blind Spots.
- **Internal, absorbed:**
  - #1816's method. Its green column was three serial passes on a quiet host, and its red column was mutants on a quiet host; neither reproduced the load. This contract keeps the mutants, runs them for parity on the base and the candidate and under the stressor, and adds stressor rows in which the base must fail and the candidate pass.
  - F-23 (PR #1758): hold the module's clock.
  - W2 (`:715`): read the production bound before lowering it.
- **Blind spots, decided:**
  - A spawn-entry delay would not reach m5 (`isolation.py:889`), so the probe suspends the child instead.
  - #1820's evidence misread which unit was refused; corrected in section 12.
  - The ledger's status-word window; the `PROGRESS.md` head avoids it.

## 14. Acceptance criteria

1. Checks O1 to O6 pass on the oracle before the build; L1 to L7 fail on the base as stated.
2. Section 8.2's counts match the base, and the six changed tests pass three times serially.
3. L1 to L4, L6 and L7 pass on the candidate; L5 fails on the candidate at the last-poll assertion.
4. The parity rule of 8.4 holds for every row, on one recorded tree.
5. The diff is exactly the files of section 9 item 1, and the ledger check passes.
6. One canonical gate with a receipt is run and resolved per 8.5, and the worker text in the candidate matches its outcome.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle trees (the orchestrator, 2026-11-24)

The base is a clean detached tree at `542a2a68`. The candidate is a second tree at `542a2a68` with every pair of section 6 applied and the ledger regenerated (its tree id is `2934e5a15aa9`, as it has no commit). Nothing else ran on the host during a row. The stressor, its harness and the mutation harness are outside the repository; the stressor is the script of section 8.3.

- **O1.** The 18 SEARCH blocks of section 6 occur once each (`contract_tools.py apply --dry --prefix 6.`), and the whitespace-insensitive check (`ws_ambiguity.py`) finds 0 hazards. The ledger check passes on the candidate.
- **O2 and O3.** O2 finds one match, `tests/test_ward_room_identity_keys.py:363` (a test name in another file; the row of 8.1 says so). O3 finds none.
- **O4, base.** The command of 8.2: 331 passed, 3 skipped in 344 s. The three skips are POSIX-only cases (`tests/test_bf893_process_tree.py:552` and `:568`, `tests/test_run_test_gate.py:1972`).
- **8.2, candidate.** The same command: 331 passed, 3 skipped in 337 s, the counts of the base (the third skip moved from `tests/test_run_test_gate.py:1972` to `:1982` with the new helper).
- **Six changed tests, three serial runs (candidate).** 7 passed in 13.3 s, 13.2 s and 13.2 s (the six tests are seven cases; A1 runs two), on a quiet host.

### 15.1 Stressor rows L1 to L7 (section 8.3)

| Row | Base (`542a2a68`) | Candidate |
|---|---|---|
| L1, `hold` 6.0 | FAILED at `premise: the grandchild never started` (`tests/test_bf893_process_tree.py:367`, called from `:967`); 2 `suspend` rows | PASSED (19 s); 2 `suspend` rows |
| L2, `hold` 6.0 | FAILED at `assert agreed.verified is True` (`tests/test_bf893_process_tree.py`, the red team's first re-run); 2 `suspend` rows | PASSED (21 s); 3 `suspend` rows |
| L3, `hold` 6.0 | FAILED: `TimeoutError` from `_wait_until(started.exists, timeout=15)` (`tests/test_ad1246_long_run_promotion.py:716`); 1 `suspend` row | PASSED (15 s); 2 `suspend` rows |
| L4, `gitlist_alternate` | FAILED: `CalledProcessError`, exit status 128, at `tests/test_run_test_gate.py:1924`; 1 `gitlist_fail` row | PASSED; 8 `gitlist_fail` rows |
| L5, `gitlist_after_kill` | FAILED: `CalledProcessError` at `:1947` (after the wrapper was killed); 2 `gitlist_fail` rows | FAILED at `assert listing is not None, "the last poll could not list the worktrees, so the registration is unknown"` (`:1970`); 149 `gitlist_fail` rows |
| L6, `identity_hold` 0.5 | both cases FAILED: `IdentityUnitUnsettled` at `tests/test_bf885_identity_db_units.py:999`; `armed` before every `end_held` (2 `end_held` rows) | both cases PASSED; `armed` before every `end_held` (11 `end_held` rows) |
| L7, `clock` | FAILED at `assert 1000.0000000002328 <= 1000.0` | PASSED |

Every `suspend` row has `ok: true`; no row printed `BF981 PROBE NOT APPLIED`.

### 15.2 Mutation rows (section 8.4), one row at a time, each file restored byte for byte (the `git status` of the base is clean after its run, and of `src` and `scripts` on the candidate)

Files under test (LF sha256, first 16 hex digits). Product and script files, the same on both trees: `scripts/_gate_process_supervisor.py` `aa41e61faf5b98f3`, `src/probos/agents/red_team.py` `c8801d8c650e465e`, `src/probos/execution/long_runs.py` `9bd193c88e2be2b4`, `src/probos/identity.py` `1a0ad74d19b78a57`. Test files, base then candidate: `tests/test_ad1246_long_run_promotion.py` `c29e104e5964537b` / `89b9e943b4e8c27a`, `tests/test_ad1246_long_run_units.py` `519b2c82dae4f986` / `8284f4df8044f70a`, `tests/test_bf885_identity_db_units.py` `efaa577dedf83870` / `0af0a9e04ebc1d0d`, `tests/test_bf893_process_tree.py` `242e05f37060647b` / `368394ec03a9216e`, `tests/test_run_test_gate.py` `e06bb97cab51d857` / `8c6308374dfc956a`.

| Row | Base, quiet | Candidate, quiet | Candidate, under the stressor |
|---|---|---|---|
| RT1 | KILLED (`a descendant was still beating after the call ended`) | KILLED (same) | KILLED, L1 (2 `suspend` rows) |
| RT2 | KILLED (`['hold', 'cancel'] == ['hold', 'release']`) | KILLED (same) | KILLED, L2 (2 `suspend` rows) |
| H1 | KILLED (`assert not gate_root.exists()`) | KILLED (same) | KILLED, L4 (49 `gitlist_fail` rows) |
| M5a | KILLED (`KeyError: 'wall_clock'`) | KILLED (same) | KILLED, L3 (2 `suspend` rows) |
| M5c | **SURVIVED** | **SURVIVED** | **SURVIVED**, L3 |
| F1a | KILLED (`1500.0 <= 1000.0`) | KILLED (`1500.0 == 1000.0`) | (no stressor) |
| B1 | KILLED, `[birth]` case only (`assert 4 == 3`, the `_anchor` check) | KILLED, `[birth]` case only (same) | KILLED, L6, `[birth]` case only |

The rule of 8.4 holds: the candidate is killed wherever the base is killed, quiet and under the stressor. Three findings for the Architect (none stops the slice):
1. **M5c survives the M5 case on both trees.** The first run's wall-clock note rides the result only when that run is cut by its limit, which the first run of the M5 case never is, so `if applied >= wanted:` -> `if False:` is invisible to it. The plan-level cases of `tests/test_ad1246_long_run_units.py` kill it (a run of that file with the mutant: KILLED). The contract's expected killer for M5c (`assert "wall_clock" not in first.output`) was wrong; the row stays in the campaign as a recorded survivor with its killer elsewhere.
2. **B1 is killed by the `[birth]` case only.** The mutant sits in `issue_birth_certificate`, which the `[transfer]` case does not use. The row's selector runs both cases; the contract's "A1 `[birth]`" is right.
3. **L1 on the base fails at the grandchild-start premise** (`_heartbeat_is_running`, 20 s wait) and not at the outer-timeout assertion. The contract's "fails at a test assertion" holds (the premise is an `assert`), and the cause named there (the budget ends while the child is held) is consistent with the 2026-11-15 and 2026-11-19 failures; it was not isolated further.
