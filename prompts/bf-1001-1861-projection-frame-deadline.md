# BF-1001 (#1861): the live crew-session projection test waits for its first semantic frame by a deadline, not by 500 polls

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Status:** ready to build. **Owning issue:** #1861. Commits and the PR body say `Refs #1861.`
**Base:** the orchestrator's base at item start (read at `6539f04d`; the test file is unchanged since `0cbf68d7`, 2026-11-25). Branch `fix/projection-frame-deadline-1861`. **Number:** BF-1001, allocated by the issue title.
**Line endings:** the index is LF and the working copies are CRLF (`git ls-files --eol`); the blocks below are LF, so match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 4 new in `tests/test_ad1133_live_crew_session_refresh.py`; 1 renamed; 1 extended; 0 removed.
**Scope:** one slice, M1. Files: `tests/test_ad1133_live_crew_session_refresh.py`, `PROGRESS.md`, `DECISIONS.md` and the regenerated ledger pair. No file under `src/`, `scripts/` or any pytest or CI configuration changes.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `test_ad1133_live_crew_session_refresh.py`:440-445 | `_wait_until` polls 500 times with `asyncio.sleep(0.002)` and then raises `condition did not become true` | its budget is a count of polls; measured on the gate host under load, one sleep is median 2.26 ms, so 500 polls are about 1.2 s |
| :2421-2422 | `receive_semantic_frame` spends that one budget on every heartbeat and the first semantic frame | the frame must arrive within about 1.2 s of the call |
| :2645 -> :2609 | `assert_consumers(200, 1003)` waits for a `crew_session_projection` over 200 active and 1,003 retired children | under a 16-worker gate on a busy host the frame arrived late in two of three gates of one commit (#1861) |

## 2. Overview

`_wait_until` gains a keyword-only `timeout_s: float | None = None`. With `None` its 500-poll loop is unchanged. With a value it waits until a `time.monotonic()` deadline, reading the predicate before each deadline check. A new module constant `_SEMANTIC_FRAME_TIMEOUT_S = 15.0` is the default of a new keyword `timeout_s` on `_ProjectionWebSocket.receive_semantic_frame`, which passes it on. The heartbeat checks (:2408-2418) are untouched.

Rejected, one line each:
- A deadline for all 48 call sites: no evidence that any other caller fails.
- A separate deadline loop in `receive_semantic_frame`: a second poll loop, and the one-budget test would count no budget.
- Awaiting `self.frames.get()` under `asyncio.wait_for`: moves the heartbeat checks out of the predicate, which #1861 keeps unchanged.
- Lowering `--workers`, a retry, or `skip`: BF-981 D3 (`DECISIONS.md`:592).
- A timed reproduction (a frame due 2 s after the call): whether it is red on the base depends on the host's timer and load; the counted one is red on every host.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | `timeout_s` defaults to `None`, keeping the 500-poll loop as it is on the base | 22 other calls in this file, 22 in `tests/test_bf997_ws_snapshot_and_work_state_resync.py` and 3 in `tests/test_ad1174_live_tool_progress.py` keep their budget (Absence A3) |
| D2 | The deadline loop reads the predicate before each deadline check | a frame queued during the last sleep, or already queued at a zero deadline, is read (pinned by the zero-deadline test) |
| D3 | The deadline is 15.0 s | above 12 times the 1.2 s budget that ran out and below pytest-timeout's 180 s (`pyproject.toml`:190); a passing wait returns when the frame arrives. Row L2 amends it to 30.0 if the large wait measures above 5.0 s under the burn |
| D4 | The deadline is a keyword of `receive_semantic_frame`, read from the module constant as its default | the never-arrives test passes 0.05 s, so it stays quick; the one-budget test asserts that the call passes the constant |
| D5 | The reproduction is counted, not timed (`_LateFrames`, 501 empty reads) | the wait on the base ends after 500 reads on any host; on the candidate, 503 reads take about 1.1 s at the measured 2.26 ms per sleep |
| D6 | The empty-queue test runs inside a 10 s `asyncio.wait_for` | a wait that never ends (W2) or that ignores the argument (W6, 15 s) fails the test instead of hanging until pytest-timeout |
| D7 | The empty-queue test is renamed `..._fails_at_its_deadline` | its old name says "existing budget", which is no longer true; the name has no reference outside the file (Absence A6) |

## 4. Milestones and commits

- **C0:** this contract. Subject: `Contract: the live crew-session projection test waits for its frame by a deadline`
- **M1:** P1 to P8, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `The live crew-session projection test waits for its first frame by a deadline`
- **PR title:** `The live crew-session projection test waits for its first frame by a deadline (#1861)`. Body opens `Refs #1861`.

No subject or title carries an `AD-` or `BF-` token or the words close, fix or resolve. Stage explicit paths only.

## 5. Builder: may and may not

- **May:** apply P1 to P8 in order, run `gen_ad_ledger.py`, `git diff --check`, `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file, change a sleep interval or a worker count, add `skip`, `xfail` or a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `tests/test_ad1133_live_crew_session_refresh.py`

**P1** (`_wait_until`, :440-445). SEARCH:
```python
async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("condition did not become true")
```
REPLACE:
```python
async def _wait_until(
    predicate: Callable[[], bool], *, timeout_s: float | None = None,
) -> None:
    """Poll ``predicate`` every 2 ms until it is true.

    With no ``timeout_s`` the wait ends after 500 polls. With ``timeout_s`` it
    ends at a wall-clock deadline that many seconds after the call; the
    predicate is read before each deadline check, so a value set during the
    last sleep is seen.
    """
    if timeout_s is None:
        for _ in range(500):
            if predicate():
                return
            await asyncio.sleep(0.002)
        raise AssertionError("condition did not become true")
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.002)
```

**P2** (the constant, before :2373). SEARCH:
```python
class _ProjectionWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
```
REPLACE:
```python
# The over-1000-retired case of test_owned_replan_current_projection_chain
# waits for a projection over 200 active and 1,003 retired children. A budget
# of 500 polls (about 1.2 s on the gate host) ran out under gate load (#1861).
_SEMANTIC_FRAME_TIMEOUT_S = 15.0


class _ProjectionWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
```

**P3** (:2399-2400). SEARCH:
```python
    async def receive_semantic_frame(self) -> dict[str, Any]:
        semantic_frame: dict[str, Any] | None = None
```
REPLACE:
```python
    async def receive_semantic_frame(
        self, *, timeout_s: float = _SEMANTIC_FRAME_TIMEOUT_S,
    ) -> dict[str, Any]:
        semantic_frame: dict[str, Any] | None = None
```

**P4** (:2421-2423). SEARCH:
```python
        # One existing budget covers all heartbeats and the first semantic frame.
        await _wait_until(receive)
        assert semantic_frame is not None
```
REPLACE:
```python
        # One deadline covers all heartbeats and the first semantic frame.
        await _wait_until(receive, timeout_s=timeout_s)
        assert semantic_frame is not None
```

**P5** (the one-budget test, :2437-2450). SEARCH:
```python
    wait_until = _wait_until
    budgets = 0

    async def counted_wait(predicate: Callable[[], bool]) -> None:
        nonlocal budgets
        budgets += 1
        await wait_until(predicate)

    monkeypatch.setattr(f"{__name__}._wait_until", counted_wait)

    assert await websocket.receive_semantic_frame() is expected
    assert websocket.pings_consumed == 2
    assert budgets == 1
    assert websocket.frames.empty()
```
REPLACE:
```python
    wait_until = _wait_until
    budgets: list[float | None] = []

    async def counted_wait(
        predicate: Callable[[], bool], *, timeout_s: float | None = None,
    ) -> None:
        budgets.append(timeout_s)
        await wait_until(predicate, timeout_s=timeout_s)

    monkeypatch.setattr(f"{__name__}._wait_until", counted_wait)

    assert await websocket.receive_semantic_frame() is expected
    assert websocket.pings_consumed == 2
    assert budgets == [_SEMANTIC_FRAME_TIMEOUT_S]
    assert websocket.frames.empty()
```

**P6** (the empty-queue test, :2522-2528, and four new tests after it). SEARCH:
```python
async def test_receive_semantic_frame_empty_queue_exhausts_existing_budget() -> None:
    websocket = _ProjectionWebSocket()

    with pytest.raises(AssertionError, match="condition did not become true"):
        await websocket.receive_semantic_frame()

    assert websocket.pings_consumed == 0
```
REPLACE:
```python
async def test_receive_semantic_frame_empty_queue_fails_at_its_deadline() -> None:
    websocket = _ProjectionWebSocket()
    started = time.monotonic()

    # The outer bound turns a wait that never ends into a failure of this test.
    with pytest.raises(AssertionError, match="condition did not become true"):
        await asyncio.wait_for(
            websocket.receive_semantic_frame(timeout_s=0.05), timeout=10.0,
        )

    # The deadline was 0.05 s; 0.01 s absorbs float rounding of the clock.
    assert time.monotonic() - started >= 0.04
    assert websocket.pings_consumed == 0


class _LateFrames(asyncio.Queue[dict[str, Any]]):
    """A frame queue that reads as empty for its first ``empty_reads`` reads."""

    def __init__(self, empty_reads: int, *frames: dict[str, Any]) -> None:
        super().__init__()
        self.empty_reads = empty_reads
        self.reads = 0
        for frame in frames:
            self.put_nowait(frame)

    def get_nowait(self) -> dict[str, Any]:
        self.reads += 1
        if self.reads <= self.empty_reads:
            raise asyncio.QueueEmpty
        return super().get_nowait()


async def test_receive_semantic_frame_receives_a_frame_later_than_500_polls() -> None:
    websocket = _ProjectionWebSocket()
    expected = {"type": "crew_session_projection", "data": {"parent_id": "parent"}}
    frames = _LateFrames(501, {"type": "ping", "timestamp": 0}, expected)
    websocket.frames = frames

    assert await websocket.receive_semantic_frame() is expected
    assert frames.reads == 503
    assert websocket.pings_consumed == 1


async def test_receive_semantic_frame_reads_a_queued_frame_at_a_zero_deadline() -> None:
    websocket = _ProjectionWebSocket()
    expected = {"type": "crew_session_projection", "data": {"parent_id": "parent"}}
    websocket.frames.put_nowait(expected)

    assert await websocket.receive_semantic_frame(timeout_s=0.0) is expected


async def test_wait_until_without_a_deadline_keeps_its_500_polls() -> None:
    polls = 0

    def never() -> bool:
        nonlocal polls
        polls += 1
        return False

    with pytest.raises(AssertionError, match="condition did not become true"):
        await _wait_until(never)

    assert polls == 500


def test_the_semantic_frame_deadline_is_finite_and_above_the_poll_budget() -> None:
    # 500 polls took about 1.2 s on the gate host (#1861); pytest-timeout is 180 s.
    assert math.isfinite(_SEMANTIC_FRAME_TIMEOUT_S)
    assert 5.0 <= _SEMANTIC_FRAME_TIMEOUT_S <= 30.0
```

### 6.2 `PROGRESS.md`

**P7.** SEARCH (line 1 and the blank line after it):
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**BF-1001 (2026-11-27), #1861 -- the live crew-session projection test waits for its first semantic frame by a 15 s deadline, not by 500 polls.** Test only. In `tests/test_ad1133_live_crew_session_refresh.py`, `_wait_until` takes an optional `timeout_s`: with it the wait ends at a `time.monotonic()` deadline and the predicate is read before each deadline check; without it the wait keeps its 500 polls of 2 ms, so its 22 other calls in the file and its 25 calls in `tests/test_bf997_ws_snapshot_and_work_state_resync.py` and `tests/test_ad1174_live_tool_progress.py` are unchanged. `_ProjectionWebSocket.receive_semantic_frame` passes `_SEMANTIC_FRAME_TIMEOUT_S` (15.0 s); its heartbeat checks are unchanged. Cause: the over-1000-retired case of `test_owned_replan_current_projection_chain` waits for a projection over 200 active and 1,003 retired children, and 500 polls (about 1.2 s on the gate host) ran out in two of three 16-worker gates of one commit on a busy host. New: `test_receive_semantic_frame_receives_a_frame_later_than_500_polls` (red on the base: its queue reads empty 501 times), `test_receive_semantic_frame_reads_a_queued_frame_at_a_zero_deadline`, `test_wait_until_without_a_deadline_keeps_its_500_polls` and `test_the_semantic_frame_deadline_is_finite_and_above_the_poll_budget`; the empty-queue test becomes `test_receive_semantic_frame_empty_queue_fails_at_its_deadline` (a 0.05 s deadline inside a 10 s outer bound), and the one-budget test also asserts the deadline it was given. Under load (rows kept outside the repository, contract section 8.3): <L2: candidate n of 10 passed under k burners, largest frame wait x s; base m of 10>; the canonical gate ran beside <L3: n runs of the case, all passed, largest frame wait x s>. Mutation census: <n> of 12 killed (rows W1 to W12, run once on the candidate overlay of `<base>`). Contract `prompts/bf-1001-1861-projection-frame-deadline.md`.

```
The orchestrator fills the three `<...>` slots from section 15 and changes nothing else. If the build day (UTC) is not 2026-11-27, it changes the date in P7 and P8.

### 6.3 `DECISIONS.md`

**P8.** SEARCH (`DECISIONS.md`:11 and the blank line after it):
```markdown
## Era V — Civilization (Phases 31-36)

```
REPLACE:
```markdown
## Era V — Civilization (Phases 31-36)

### BF-1001 -- The live crew-session projection test waits for its first semantic frame by a deadline (2026-11-27, #1861)

- *Scope.* `tests/test_ad1133_live_crew_session_refresh.py` only. Contract: `prompts/bf-1001-1861-projection-frame-deadline.md`.
- *Cause.* `receive_semantic_frame` waited 500 polls of 2 ms (about 1.2 s on the gate host). The over-1000-retired case's projection over 200 active and 1,003 retired children arrived later under gate load in two of three gates of one commit. No product code is implicated.
- *D1.* `_wait_until` takes an optional `timeout_s`, a `time.monotonic()` deadline; without it the 500-poll budget stays for its other call sites (BF-981 D1: a budget that is not under test is raised far above the start; budgets that no evidence implicates are left).
- *D2.* The frame deadline is 15.0 s: above 12 times the budget that ran out and below pytest-timeout's 180 s; a passing wait returns when the frame arrives, so the deadline costs time only in a failing run. A test pins it finite and between 5 s and 30 s.
- *D3.* The discriminating test is counted, not timed: a queue that reads empty 501 times fails the 500-poll wait on any host and passes the deadline.
- *Rejected.* A deadline for all 48 call sites (no evidence that the others fail); a separate loop in `receive_semantic_frame` (a second poll loop, and the one-budget test would count none); awaiting the queue directly (moves the heartbeat checks out of the predicate); lowering `--workers` (BF-981 D3).
- *Reversal.* Revert the commit. Nothing persisted changes.

```

## 7. Consumers

| Consumer | What it needs | Effect |
|---|---|---|
| 22 other `_wait_until` calls in this file | the 500-poll path | unchanged (`timeout_s` is `None`) |
| `tests/test_bf997_ws_snapshot_and_work_state_resync.py`:22 (import) and its 22 calls | the 500-poll path | unchanged |
| `tests/test_ad1174_live_tool_progress.py`:21 (module import), :193, :196, :219 | the 500-poll path | unchanged |
| the five `receive_semantic_frame` calls (:2447, :2476, :2517, :2526, :2609) | the semantic frame, heartbeats checked | the default deadline applies; :2526 becomes the 0.05 s case |
| `tests/test_ad1184_ad_ledger.py` | the ledger pair current | regenerated in M1 |

## 8. Gates (the orchestrator runs all of them)

### 8.1 On the oracle tree, before the Builder starts

| # | Check | Expected |
|---|---|---|
| O1 | each SEARCH of section 6, LF-normalised, counted in its file at its turn | 1 each |
| O2 | `rg -n "_SEMANTIC_FRAME_TIMEOUT_S\|_LateFrames\|timeout_s" tests/test_ad1133_live_crew_session_refresh.py` | no match |
| O3 | base counts of the focused command (8.2) | record them; the candidate is the base plus 4 |
| O4 | rows L1 and L2 (8.3) on the base | record them (diagnostic: a base failure under L2 confirms that the load reproduces the flake; a base pass does not void the evidence) |
| O5 | W11 and W12 (8.4) on the base | KILLED (parity reference) |

### 8.2 Focused check on the candidate

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1133_live_crew_session_refresh.py tests/test_bf997_ws_snapshot_and_work_state_resync.py tests/test_ad1174_live_tool_progress.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
```
Expected: O3 counts plus 4, all passed. Then `scripts/gen_ad_ledger.py --check` reports current, and `scripts/run_test_gate.py --preflight-only --label bf-1001-1861` exits 0.

AB1, the red proof: the base plus only the `_LateFrames` class and `test_receive_semantic_frame_receives_a_frame_later_than_500_polls` from P6 (an uncommitted overlay); run that one test: 1 failed, `AssertionError: condition did not become true`. On the candidate: 1 passed.

### 8.3 Load rows (`-n 0 -p no:randomly`, win32, outside the repository)

Two files in a new directory outside the repository that holds nothing else: `frame_probe.py` (a pytest plugin) and `burn_ab.py`.

```python
# frame_probe.py -- BF-1001 load probe; not part of the repository.
import json
import os
import sys
import time

MODULE = "tests.test_ad1133_live_crew_session_refresh"


def pytest_collection_finish(session):
    module = sys.modules[MODULE]  # a KeyError voids the row
    original = module._ProjectionWebSocket.receive_semantic_frame

    async def timed(self, *args, **kwargs):
        started = time.monotonic()
        outcome = "raised"
        try:
            frame = await original(self, *args, **kwargs)
            outcome = "frame"
            return frame
        finally:
            with open(os.environ["FRAME_PROBE_LOG"], "a", encoding="ascii") as log:
                log.write(json.dumps({
                    "elapsed_s": round(time.monotonic() - started, 4),
                    "outcome": outcome,
                }) + "\n")

    module._ProjectionWebSocket.receive_semantic_frame = timed
```

```python
# burn_ab.py -- BF-1001 load rows; not part of the repository.
# Usage: python -I burn_ab.py <python> <log_dir> <burners> <runs> <label>=<tree> [...]
import json
import os
import subprocess
import sys
import time
from pathlib import Path

NODE = ("tests/test_ad1133_live_crew_session_refresh.py::"
        "test_owned_replan_current_projection_chain[over-1000-retired]")
HERE = Path(__file__).resolve().parent


def main() -> None:
    python, log_dir, burners, runs = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    trees = [arg.split("=", 1) for arg in sys.argv[5:]]
    log_dir.mkdir(parents=True, exist_ok=True)
    burn = [subprocess.Popen([sys.executable, "-I", "-c", "while True: pass"]) for _ in range(burners)]
    try:
        for index in range(runs):
            for label, tree in trees:
                probe_log = log_dir / f"{label}-{index}.jsonl"
                env = dict(os.environ, FRAME_PROBE_LOG=str(probe_log),
                           PYTHONPATH=os.pathsep.join([str(Path(tree) / "src"), str(HERE)]))
                started = time.monotonic()
                done = subprocess.run(
                    [python, "-m", "pytest", NODE, "-n", "0", "-p", "no:randomly", "-q", "-p", "frame_probe"],
                    cwd=tree, env=env, capture_output=True, text=True)
                waits = probe_log.read_text(encoding="ascii").splitlines() if probe_log.exists() else []
                print(json.dumps({"label": label, "run": index, "exit": done.returncode,
                                  "wall_s": round(time.monotonic() - started, 1),
                                  "waits": [json.loads(line) for line in waits]}), flush=True)
    finally:
        for proc in burn:
            proc.kill()
        for proc in burn:
            proc.wait()


main()
```

| Row | Command shape | Expected |
|---|---|---|
| L1 quiet | `burners 0, runs 3, base=<base tree> cand=<candidate tree>` | both 3 of 3 exit 0; record each run's two waits |
| L2 burn | `burners <os.cpu_count()>, runs 10`, base and candidate interleaved | candidate 10 of 10 exit 0, and its largest second wait (the 200/1,003 frame) is at most 5.0 s; above 5.0 s, amend D3 to 30.0 and re-run L2. Base: record (diagnostic) |
| L3 gate | `burners 0, runs <until the gate ends>, cand=<candidate tree>`, started when the canonical gate starts and stopped when it ends | every run exits 0; record the count and the largest wait |

Record for each row: the host's `os.cpu_count()`, the burner count, start and end times (UTC), per-run exit codes and waits.

### 8.4 Mutation rows (one at a time on the candidate overlay; restore byte for byte; record each file's sha256 and the base as the campaign of record)

| Row | Mutant | Expected killer |
|---|---|---|
| W1 | P4's call is `await _wait_until(receive)` | `..._later_than_500_polls` (raises after read 500); one-budget test (`[None]`) |
| W2 | the deadline loop drops its `if time.monotonic() >= deadline:` check and raise | `..._fails_at_its_deadline` (the 10 s outer bound raises `TimeoutError`) |
| W3 | `_SEMANTIC_FRAME_TIMEOUT_S = math.inf` | `test_the_semantic_frame_deadline_is_finite_and_above_the_poll_budget` |
| W4 | `_SEMANTIC_FRAME_TIMEOUT_S = 1.0` | the same |
| W5 | `deadline = time.monotonic()` | `..._fails_at_its_deadline` (elapsed below 0.04 s); `..._later_than_500_polls` |
| W6 | `deadline = time.monotonic() + 15.0` | `..._fails_at_its_deadline` (outer bound at 10 s) |
| W7 | the deadline check moved before the predicate read (`while True:` check, then read, then sleep) | `..._reads_a_queued_frame_at_a_zero_deadline` |
| W8 | the no-deadline loop is `range(501)` | `test_wait_until_without_a_deadline_keeps_its_500_polls` |
| W9 | `if timeout_s is None: timeout_s = 15.0` as the first line of `_wait_until` (followed by the unchanged `if timeout_s is None:` branch, now dead) | `test_wait_until_without_a_deadline_keeps_its_500_polls` (polls far above 500, after 15 s) |
| W10 | `receive_semantic_frame` default `timeout_s: float = 0.05` | one-budget test (`[0.05]`); `..._later_than_500_polls` |
| W11 | delete `assert set(frame) == {"type", "timestamp"}, "malformed heartbeat envelope"` | `test_receive_semantic_frame_rejects_malformed_heartbeat[extra-data]`, `[extra-stream]` (base and candidate) |
| W12 | delete `self.pings_consumed += 1` | one-budget test (base and candidate); `..._later_than_500_polls` (candidate) |

Not run, equivalent: `>=` to `>` in the deadline check (the predicate read comes first, so no case can tell them apart on a clock that advances).

### 8.5 The broad gate

After the Diff Reviewer approves and M1 is committed locally, and with the base merged in first: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-1001-1861 --receipt logs/gates/bf-1001-1861.receipt.json`, at the default 16 workers, with row L3 running beside it. If a different test fails under the added load, triage it under **Gate workers** (`.github/agents/orchestrator.agent.md`): it is not this item's failure, and it does not replace L3's record.

## 9. Diff Reviewer: properties to verify

1. A call of `_wait_until` without `timeout_s` behaves as on the base: 500 reads, 2 ms sleeps, the same message.
2. With `timeout_s`, the predicate is read at least once and before each deadline check; the raise message is unchanged.
3. No line of :2408-2418 (the heartbeat checks) is in the diff.
4. `receive_semantic_frame` passes its own `timeout_s`, defaulting to the module constant.
5. `..._fails_at_its_deadline` cannot hang: its 10 s outer bound is below W6's 15 s.
6. `..._later_than_500_polls` is red on the base on any host (AB1), independent of the timer resolution.
7. No sleep interval, worker count, `skip`, `xfail` or retry changes; no file outside section 6 and the ledger pair changes.
8. The PROGRESS and DECISIONS text states only what the rows measured; the ledger pair is regenerated.

## 10. Verified Against Codebase (2026-11-26, tree `6539f04d`)

```
tests/test_ad1133_live_crew_session_refresh.py
  :8 import math | :9 import time | :12 from typing import Any, Callable
  :440-445 _wait_until, for _ in range(500) ... asyncio.sleep(0.002) ... raise AssertionError("condition did not become true")
  :2373 class _ProjectionWebSocket(_FakeWebSocket): | :2376 self.frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue() | :2378 self.pings_consumed = 0
  :2383 self.frames.put_nowait(json.loads(payload))
  :2399 async def receive_semantic_frame(self) -> dict[str, Any]: | :2405 self.frames.get_nowait()
  :2408-2418 heartbeat checks | :2421 "# One existing budget covers ..." | :2422 await _wait_until(receive)
  :2428 test_receive_semantic_frame_valid_heartbeats_share_one_budget | :2440 counted_wait | :2445 monkeypatch.setattr(f"{__name__}._wait_until", counted_wait) | :2449 assert budgets == 1
  :2522 test_receive_semantic_frame_empty_queue_exhausts_existing_budget | :2525 pytest.raises(AssertionError, match="condition did not become true")
  :2531 parametrize large_history ids small, over-1000-retired | :2609 frame = await websocket.receive_semantic_frame() | :2623 assert_consumers(2, 1) | :2626 replan_decomposer.count = 200 | :2643 == 1003 | :2645 assert_consumers(200, 1003)
pyproject.toml :181 asyncio_mode = "auto" | :190 timeout = 180 | :196 addopts = "-n 16 --dist=loadfile"
src/probos/crew_session_live.py :64 get_owned_crew_children | :132 observe_crew_children | :138, :146 get_work_item | :142 get_session | :170 load_fenced_crew_children | :400 load_crew_session_projection | :410, :432 asyncio.to_thread | :440-441 self._publish("crew_session_projection", ...)
src/probos/ws_event_stream.py :742-745 receive_text under a 30.0 s wait_for | :747-752 a ping queued on that timeout
tests/test_bf997_ws_snapshot_and_work_state_resync.py :22 from tests.test_ad1133_live_crew_session_refresh import _FakeWebSocket, _Runtime, _wait_until
tests/test_ad1174_live_tool_progress.py :21 import as live | :193, :196, :219 live._wait_until(
Prior art: tests/test_ad1195_durable_event_seam.py :247-251; tests/fixtures/issue1375_work_state_bridge.py :92 WAIT_SECONDS = 5.0, :246-251; tests/test_bf824_pool_health_loop_survives.py :101-105; DECISIONS.md :590 (BF-981 part 2 D1), :592 (D3)
Trackers: PROGRESS.md :1 "# ProbOS Progress"; DECISIONS.md :11 "## Era V — Civilization (Phases 31-36)", :13 newest entry
git ls-files --eol: the three edited files are i/lf w/crlf
Last change to the test file: 0cbf68d7 (2026-11-25)
```

### Absence Verified (2026-11-26)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | `_ProjectionWebSocket` has no consumer outside this file | Grep `test_ad1133_live_crew_session_refresh\|_ProjectionWebSocket` over the repo | `_ProjectionWebSocket` only in this file (:2373, :2432, :2470, :2489, :2523, :2563, :2703); the module name in two test files (A3), `tests/fixtures/file_durations.json`:108 (a duration key), `PROGRESS.md` and `prompts/` | yes |
| A2 | `receive_semantic_frame` is named only in this file | Grep count over `{src,tests,scripts,ui}/**` | this file 10 (the definition, 5 calls, 4 test names) | yes |
| A3 | `_wait_until` from this file has only two importers | Grep `_wait_until\(` in the three files; Grep `_wait_until` over `{src,scripts}/**` | 24 (incl. the definition), bf997 22, ad1174 3; src and scripts 0 | yes |
| A4 | only one test patches `_wait_until` | Grep `monkeypatch\.setattr\([^)]*_wait_until` over tests | :2445 | yes |
| A5 | the new names are free | Grep `_SEMANTIC_FRAME_TIMEOUT_S\|_LateFrames` over `{src,tests,scripts,ui}/**`; `timeout_s` in this file | 0; 0 | yes |
| A6 | the renamed test and the one-budget test are not named elsewhere | Grep `empty_queue_exhausts_existing_budget\|valid_heartbeats_share_one_budget` over the repo | this file only | yes |
| A7 | no other `_wait_until` caller waits on a producer over 1,000 rows | Grep `1003\|1_00\d\|range\(1\d\d\d\|count = \d{3}\|large_history` in the file, compared with the `_wait_until` call lines | :1708-1922 are direct `build_bounded_hxi_snapshot_base()` calls; :2356 lies between calls :2243 and :2422; :2626-2645 is this case | yes |
| A8 | only one test matches the wait's message | Grep `condition did not become true` over tests | :445 (the raise), :2525 | yes |
| A9 | no failure evidence for the other 500-iteration poll | Grep `for _ in range\(500\)` over tests | `test_bf887_continue_resumes_the_promoted_turn.py`:527 (10 ms polls); `test_bf746_mcp_sse_framing.py`:144 is not a poll; #1861 and #1815 name neither | yes |

## 11. What this does NOT change, and recorded limits

- No product code, sleep interval, worker count or pytest setting.
- The 22 other calls in this file and the 25 in the two importing files keep the 500-poll budget.
- L1. The unbounded `await websocket.frames.get()` waits at :2618, :2706, :2724, :2737 stay; a lost frame there hangs until pytest-timeout (180 s) instead of failing early. No flake is recorded for them.
- L2. `test_bf887_continue_resumes_the_promoted_turn.py`:527 keeps its 500 x 10 ms loop; no failure evidence.
- L3. On CPython 3.12 for Windows `time.monotonic()` ticks at about 15.6 ms (3.13 moved it to the performance counter), so the deadline is exact only to a tick; the empty-queue test's 0.04 s bound allows for it.

## 12. Issue text (#1861)

Before the gate, a comment:

> **Acceptance evidence (2026-11-27, orchestrator, decided by `claude-architect`).** Canonical gates take a host-wide lock and cannot overlap, so the first criterion is met by recorded load: row L2 (the large case 10 times on the base and 10 on the candidate, interleaved, under `os.cpu_count()` CPU burners), row L3 (the large case in a loop from the candidate tree for the whole of one canonical gate, so each run is the failing case under a live 16-worker gate) and that one canonical gate. The Captain may ask for a second gate of the same commit under the same load; that is the only addition.

After the merge, tick the four boxes, post this comment, then close #1861 as completed and verify that it is closed:

> Shipped in #<PR> (`<merge sha>`), test only: `tests/test_ad1133_live_crew_session_refresh.py`. `receive_semantic_frame` waits for its first semantic frame until a 15.0 s `time.monotonic()` deadline; `_wait_until` keeps its 500 polls for every caller that passes no deadline. Heartbeat checks (`:2408-2418` on the base) unchanged.
> - Load: L2 <result>; L3 <n> runs beside gate `bf-1001-1861`, all passed, largest frame wait <x> s; host `os.cpu_count()` <n>.
> - Bounded failure: `test_receive_semantic_frame_empty_queue_fails_at_its_deadline` (0.05 s deadline inside a 10 s outer bound).
> - Red on the base: AB1 (`..._later_than_500_polls`, a queue that reads empty 501 times).
> - Mutation census: <n> of 12 killed (W1-W12). Gate receipt `logs/gates/bf-1001-1861.receipt.json`.

## 13. Prior art and blind spots

- Internal: BF-981 part 2 D1 (`DECISIONS.md`:590), "a budget that is not under test is raised far above the start": adopted. The deadline helpers at `test_ad1195_durable_event_seam.py`:247-251 and `issue1375_work_state_bridge.py`:246-251 (a monotonic deadline, the predicate read first): adopted. `test_bf824_pool_health_loop_survives.py`:102-104, "a fixed sleep encodes how fast the box is": the cause stated.
- External: not searched. This is test plumbing with no outside design question; `docs/research/reference-projects.md` not examined for the same reason (considered, deferred: all rows).
- Blind spots: the Windows timer resolution of both `asyncio.sleep` and `time.monotonic` (D5, L3); a heartbeat produced by the hub's own 30 s receive timeout (`ws_event_stream.py`:742-752) could land inside a 15 s wait, and the predicate accepts a well-formed one; `--dist=loadfile` keeps the whole file on one worker, and the change adds about 2.4 s to it.

## 14. Acceptance criteria

- [ ] AB1 is red on the base and green on the candidate; the focused check of 8.2 passes with the base counts plus 4.
- [ ] L2 and L3 meet section 8.3; the canonical gate `bf-1001-1861` is green with its receipt.
- [ ] W1 to W12 are killed as section 8.4 states.
- [ ] Lines :2408-2418 of the base are unchanged.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle trees (the orchestrator fills this in)
