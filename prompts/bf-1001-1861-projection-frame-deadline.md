# BF-1001 (#1861): the live crew-session projection test waits for its first semantic frame by a deadline, not by 500 polls

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27, for the corrected issue text
**Status:** ready to build. **Owning issue:** #1861. Commits and the PR body say `Refs #1861.`
**Base:** the orchestrator's base at item start (read at `6539f04d`; re-read for this revision at main `d6a744d7`; the test file is unchanged since `0cbf68d7`, 2026-11-25). Branch `fix/projection-frame-deadline-1861`. **Number:** BF-1001, allocated by the issue title.
**Line endings:** the index is LF and the working copies are CRLF (`git ls-files --eol`); the blocks below are LF, so match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 4 new in `tests/test_ad1133_live_crew_session_refresh.py`; 1 renamed; 1 extended; 0 removed.
**Scope:** one slice, M1. Files: `tests/test_ad1133_live_crew_session_refresh.py`, `PROGRESS.md`, `DECISIONS.md` and the regenerated ledger pair. No file under `src/`, `scripts/` or any pytest or CI configuration changes.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `test_ad1133_live_crew_session_refresh.py`:440-445 | `_wait_until` polls 500 times with `asyncio.sleep(0.002)` and then raises `condition did not become true` | its budget is a count of polls; measured on the gate host under load, one sleep is median 2.26 ms, so 500 polls are about 1.2 s |
| :2421-2422 | `receive_semantic_frame` spends that one budget on every heartbeat and the first semantic frame | the frame must arrive within about 1.2 s of the call |
| :2645 -> :2609 | `assert_consumers(200, 1003)` waits for a `crew_session_projection` over 200 active and 1,003 retired children | the frame arrived after the budget in two 16-worker canonical gates of one docs-only commit, while the orchestrator's builders and reviewers and an architect session ran on the host; a third gate of that commit passed it. The gate lock refused a third canonical run at 03:40:31Z, so the two failing gates overlapped no other canonical gate (#1861) |

## 2. Overview

`_wait_until` gains a keyword-only `timeout_s: float | None = None`. With `None` its 500-poll loop is unchanged. With a value it waits until a `time.monotonic()` deadline, reading the predicate before each deadline check. A new module constant `_SEMANTIC_FRAME_TIMEOUT_S = 15.0` is the default of a new keyword `timeout_s` on `_ProjectionWebSocket.receive_semantic_frame`, which passes it on. The heartbeat checks (:2408-2418) are untouched.

The acceptance evidence is two consecutive 16-worker canonical gates of the committed M1 head, each with a loop of the large case (row L3) running beside it for the whole gate (D8, D9, section 8.5).

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
| D8 | The first criterion of #1861 is met by two consecutive canonical gates, G1 and G2, of the one committed M1 head, both at the wrapper's default of 16 workers (`run_test_gate.py`:1763), each with row L3 running beside it from before its start to after its end | the criterion as corrected on 2026-11-27 asks for two consecutive canonical gates under recorded extra load; both failures were 16-worker gates with other work on the host, so a gate at fewer workers carries less load than the one that failed and would show less than the criterion asks; L3 is the "parallel focused pytest run" the criterion names, and its probe times the case's frame wait, which the gate does not |
| D9 | A gate counts toward the pair when it completes, L3 covered it with every run exiting 0, and the case passed in it. A void gate (aborted before the case has an outcome, or not covered by L3) neither counts nor breaks the pair. A failure of the case, in a gate or in L3, ends the item. A gate red on a different test counts for the case; the push still needs a green receipt of the head (8.5) | the criterion names the case; #1523 F-757 (addendum of 2026-11-24) records 16-worker gates on this host aborted by pytest-timeout kills, which say nothing about the case; a failure of another test is triaged under **Gate workers** (`.github/agents/orchestrator.agent.md`) and is not this item's failure |
| D10 | `PROGRESS.md` and `DECISIONS.md` carry no gate result; the gate records go on #1861 and in the PR body | P7 and P8 are committed in M1 before the gates, and a change after a gate invalidates it (`CLAUDE.md`, Workflow step 5) |

## 4. Milestones and commits

- **C0:** this contract. Subject: `Contract: the live crew-session projection test waits for its frame by a deadline`
- **M1:** P1 to P8, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `The live crew-session projection test waits for its first frame by a deadline`
- **PR title:** `The live crew-session projection test waits for its first frame by a deadline (#1861)`. Body opens `Refs #1861`.

G2 is not a commit. G1 and G2 gate the same M1 head; nothing is committed, merged or edited in the worktree between them. A gate that a later base merge needs before the push is a gate of a new head under the orchestrator's rules and is not part of the pair.

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

**BF-1001 (2026-11-27), #1861 -- the live crew-session projection test waits for its first semantic frame by a 15 s deadline, not by 500 polls.** Test only. In `tests/test_ad1133_live_crew_session_refresh.py`, `_wait_until` takes an optional `timeout_s`: with it the wait ends at a `time.monotonic()` deadline and the predicate is read before each deadline check; without it the wait keeps its 500 polls of 2 ms, so its 22 other calls in the file and its 25 calls in `tests/test_bf997_ws_snapshot_and_work_state_resync.py` and `tests/test_ad1174_live_tool_progress.py` are unchanged. `_ProjectionWebSocket.receive_semantic_frame` passes `_SEMANTIC_FRAME_TIMEOUT_S` (15.0 s); its heartbeat checks are unchanged. Cause: the over-1000-retired case of `test_owned_replan_current_projection_chain` waits for a projection over 200 active and 1,003 retired children, and 500 polls (about 1.2 s on the gate host) ran out in two 16-worker canonical gates of one docs-only commit while other work ran on the host; a third gate of that commit passed it. New: `test_receive_semantic_frame_receives_a_frame_later_than_500_polls` (red on the base: its queue reads empty 501 times), `test_receive_semantic_frame_reads_a_queued_frame_at_a_zero_deadline`, `test_wait_until_without_a_deadline_keeps_its_500_polls` and `test_the_semantic_frame_deadline_is_finite_and_above_the_poll_budget`; the empty-queue test becomes `test_receive_semantic_frame_empty_queue_fails_at_its_deadline` (a 0.05 s deadline inside a 10 s outer bound), and the one-budget test also asserts the deadline it was given. Under CPU burners (row L2, contract section 8.3; logs kept outside the repository): <L2: candidate n of 10 passed under k burners, largest frame wait x s; base m of 10>. The acceptance evidence, two consecutive 16-worker canonical gates of this commit, each with a loop of the case running beside it (contract section 8.5), is recorded on #1861. Mutation census: <n> of 12 killed (rows W1 to W12, run once on the candidate overlay of `<base>`). Contract `prompts/bf-1001-1861-projection-frame-deadline.md`.

```
The orchestrator fills the `<L2: ...>` slot from the section 15 record of row L2, and the `<n>` and `<base>` slots from the section 15 record of rows W1 to W12 (the census and the base of the campaign of record), and changes nothing else. No slot holds a gate result (D10). If the build day (UTC) is not 2026-11-27, it changes the date in P7 and P8.

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
- *Cause.* `receive_semantic_frame` waited 500 polls of 2 ms (about 1.2 s on the gate host). The over-1000-retired case's projection over 200 active and 1,003 retired children arrived after that budget in two 16-worker canonical gates of one docs-only commit while other work ran on the host; a third gate of that commit passed it. No product code is implicated.
- *D1.* `_wait_until` takes an optional `timeout_s`, a `time.monotonic()` deadline; without it the 500-poll budget stays for its other call sites (BF-981 D1: a budget that is not under test is raised far above the start; budgets that no evidence implicates are left).
- *D2.* The frame deadline is 15.0 s: above 12 times the budget that ran out and below pytest-timeout's 180 s; a passing wait returns when the frame arrives, so the deadline costs time only in a failing run. A test pins it finite and between 5 s and 30 s.
- *D3.* The discriminating test is counted, not timed: a queue that reads empty 501 times fails the 500-poll wait on any host and passes the deadline.
- *D4.* The acceptance evidence is two consecutive canonical gates of this commit at the default 16 workers, each with a loop of the case running beside it for the whole gate, recorded on #1861: the failures were at 16 workers on a loaded host, so fewer workers would not reproduce them. Under CPU burners (row L2): <L2: candidate n of 10 passed under k burners, largest frame wait x s; base m of 10>.
- *Rejected.* A deadline for all 48 call sites (no evidence that the others fail); a separate loop in `receive_semantic_frame` (a second poll loop, and the one-budget test would count none); awaiting the queue directly (moves the heartbeat checks out of the predicate); lowering `--workers` (BF-981 D3).
- *Reversal.* Revert the commit. Nothing persisted changes.

```
The orchestrator fills the `<L2: ...>` slot of P8 with the text it puts in P7's.

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
# runs 0 (row L3): loop until the file named by BURN_AB_STOP exists.
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

NODE = ("tests/test_ad1133_live_crew_session_refresh.py::"
        "test_owned_replan_current_projection_chain[over-1000-retired]")
HERE = Path(__file__).resolve().parent


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    python, log_dir, burners, runs = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    trees = [arg.split("=", 1) for arg in sys.argv[5:]]
    stop = os.environ.get("BURN_AB_STOP")
    if runs == 0 and not stop:
        raise SystemExit("runs 0 needs BURN_AB_STOP")
    log_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"event": "start", "utc": utc(), "cpu_count": os.cpu_count(),
                      "burners": burners}), flush=True)
    burn = [subprocess.Popen([sys.executable, "-I", "-c", "while True: pass"]) for _ in range(burners)]
    index = 0
    try:
        while runs == 0 or index < runs:
            if runs == 0 and Path(stop).exists():
                break
            for label, tree in trees:
                probe_log = log_dir / f"{label}-{index}.jsonl"
                env = dict(os.environ, FRAME_PROBE_LOG=str(probe_log),
                           PYTHONPATH=os.pathsep.join([str(Path(tree) / "src"), str(HERE)]))
                run_utc = utc()
                started = time.monotonic()
                done = subprocess.run(
                    [python, "-m", "pytest", NODE, "-n", "0", "-p", "no:randomly", "-q", "-p", "frame_probe"],
                    cwd=tree, env=env, capture_output=True, text=True)
                waits = probe_log.read_text(encoding="ascii").splitlines() if probe_log.exists() else []
                print(json.dumps({"label": label, "run": index, "utc": run_utc, "exit": done.returncode,
                                  "wall_s": round(time.monotonic() - started, 1),
                                  "waits": [json.loads(line) for line in waits]}), flush=True)
            index += 1
    finally:
        for proc in burn:
            proc.kill()
        for proc in burn:
            proc.wait()
        print(json.dumps({"event": "end", "utc": utc(), "runs": index}), flush=True)


main()
```

| Row | Command shape | What it adds | Expected |
|---|---|---|---|
| L1 quiet | `burners 0, runs 3, base=<base tree> cand=<candidate tree>` | the frame waits on an unloaded host, the reference for L2 and L3 | both 3 of 3 exit 0; record each run's two waits |
| L2 burn | `burners <os.cpu_count()>, runs 10`, base and candidate interleaved | base against candidate under the same heavy load, and the size check of D3 | candidate 10 of 10 exit 0, and its largest second wait (the 200/1,003 frame) is at most 5.0 s; above 5.0 s, amend D3 to 30.0 and re-run L2. Base: record (diagnostic) |
| L3 gate | `burners 0, runs 0, cand=<L3 tree>` with `BURN_AB_STOP` set to a path that does not exist yet; one loop per gate, G1 and G2 (8.5) | the recorded extra load of the criterion, and the case's frame waits under a live 16-worker gate | every run exits 0 and each of its waits reads `frame`; the loop's start line is before the gate's start and its end line after the gate's end; record the count and the largest wait |

The L3 tree is a separate checkout of the committed M1 head (an oracle tree, not the gated worktree) whose `git rev-parse HEAD^{tree}` equals the worktree's: the wrapper hashes the gated worktree's status into its receipt (`run_test_gate.py`:1678-1679), so no L3 run writes there.

`burn_ab.py` prints the record of each row: its start line carries the UTC time, the host's `os.cpu_count()` and the burner count; each run line carries the run's UTC start, its exit code and its waits; its end line carries the UTC time and the run count. Keep its output with the probe logs, outside the repository.

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

### 8.5 The broad gates G1 and G2

After the Diff Reviewer approves and M1 is committed locally, with the base merged in first and the plan comment of section 12 posted on #1861:

1. Prepare the L3 tree (8.3) at the committed M1 head.
2. **G1.** Start the L3 loop for G1 (its own log directory and stop-file path) and wait for its start line. Record the UTC time, then launch `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-1001-1861 --receipt logs/gates/bf-1001-1861.receipt.json` with no `--workers` (the default of 16, `run_test_gate.py`:1763). When the wrapper exits, record the UTC time, create the stop file and wait for the loop's end line. The receipt holds `finished_at` (`run_test_gate.py`:1666) but not the start, which is why the launch time is recorded. Read the case's outcome in the gate from the gate's JUnit report. Post the gate's record on #1861 (section 12).
3. **G2.** The same, right after G1's record is posted, with `--label bf-1001-1861-r2 --receipt logs/gates/bf-1001-1861-r2.receipt.json` and a fresh L3 log directory and stop-file path. A further gate of the head takes the next suffix (`-r3`, ...).

Each gate's outcome decides what happens next (D9):

| Outcome of a gate of the M1 head | Counts toward the pair | Next |
|---|---|---|
| it completes, the case passed, L3 covered it and every L3 run exited 0, and the gate is green | yes | the next gate; after the second counted gate, the push |
| it completes, the case passed, L3 covered it and every L3 run exited 0, but the gate is red on a different test | yes, for the case | triage each failing test under **Gate workers** (`.github/agents/orchestrator.agent.md`) and record it on #1861 and in its own issue; it is not this item's failure. Then the next gate. The push needs a green receipt of the head, so when neither counted gate is green, run one more gate of the head with its L3 loop |
| the case failed in the gate, or an L3 run exited nonzero or recorded a wait that reads `raised` | the item ends | stop; give the gate report and the L3 log to the Architect. A repair is a new head, and its pair starts again at zero |
| void: the gate aborted before the case had an outcome (the F-757 shape on #1523: exit 3, `INTERNALERROR`, workers killed by pytest-timeout), or the L3 loop did not cover the whole gate | no, and it does not break the pair | record it on #1861 and run the next gate; after three void gates of the head, stop and report to the Architect |

"Consecutive" means: G1 and G2 are the first two counted gates of the head in the order they ran; between them there is no gate of the head in which the case failed (that would have ended the item), and a void gate between them does not separate them. A gate at fewer than 16 workers is not part of the pair (D8); if the void rule stops the item, the Architect decides whether a lower count with a measured reason (**Gate workers**) may supply the push receipt, and the pair stays at 16.

## 9. Diff Reviewer: properties to verify

1. A call of `_wait_until` without `timeout_s` behaves as on the base: 500 reads, 2 ms sleeps, the same message.
2. With `timeout_s`, the predicate is read at least once and before each deadline check; the raise message is unchanged.
3. No line of :2408-2418 (the heartbeat checks) is in the diff.
4. `receive_semantic_frame` passes its own `timeout_s`, defaulting to the module constant.
5. `..._fails_at_its_deadline` cannot hang: its 10 s outer bound is below W6's 15 s.
6. `..._later_than_500_polls` is red on the base on any host (AB1), independent of the timer resolution.
7. No sleep interval, worker count, `skip`, `xfail` or retry changes; no file outside section 6 and the ledger pair changes.
8. The PROGRESS and DECISIONS text states only what the rows measured, holds no gate result (D10), and its account of the two failing gates names no overlap of canonical gates; the ledger pair is regenerated.

## 10. Verified Against Codebase (2026-11-26, tree `6539f04d`; revision checks 2026-11-27 at main `d6a744d7`)

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
Revision checks (2026-11-27):
  git log -1 -- tests/test_ad1133_live_crew_session_refresh.py -> 0cbf68d7f303a3ee4cfe2fd63b985163f779402a
  PROGRESS.md :1 "# ProbOS Progress" | DECISIONS.md :11 the Era V heading, unchanged (the orchestrator's dry run applied P1 to P8 once each on this base)
  scripts/run_test_gate.py :1666 "finished_at": result.finished_at | :1678-1679 "status_sha256", "raw_status_sha256" | :1763 parser.add_argument("--workers", type=int, default=16) | :1801 started_at = _utc_now() (not written to the receipt: grep "started_at" finds :164, :1801, :2037 only)
  .github/agents/orchestrator.agent.md :137 Gate workers (BF-981, #1815)
  #1861 body (corrected 2026-11-27): runs orchestrator-stop-marker 03:10Z and -r2 03:40Z failed this case; the gate lock refused ad-1337-r23-r7-r1 at 03:40:31Z; -r3 04:07Z passed it
  #1523 F-757 addendum of 2026-11-24: two 16-worker gates aborted (exit 3, INTERNALERROR, pytest-timeout kills)
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
| A10 | the gate receipt holds no start time | Grep `started_at` in `scripts/run_test_gate.py` | :164 (the result field), :1801 (assigned), :2037 (passed to the result); the receipt payload at :1663-1694 has `finished_at` only | yes |

## 11. What this does NOT change, and recorded limits

- No product code, sleep interval, worker count or pytest setting.
- The 22 other calls in this file and the 25 in the two importing files keep the 500-poll budget.
- L1. The unbounded `await websocket.frames.get()` waits at :2618, :2706, :2724, :2737 stay; a lost frame there hangs until pytest-timeout (180 s) instead of failing early. No flake is recorded for them.
- L2. `test_bf887_continue_resumes_the_promoted_turn.py`:527 keeps its 500 x 10 ms loop; no failure evidence.
- L3. On CPython 3.12 for Windows `time.monotonic()` ticks at about 15.6 ms (3.13 moved it to the performance counter), so the deadline is exact only to a tick; the empty-queue test's 0.04 s bound allows for it.
- L4. The pair shows that the case passed twice under a 16-worker gate with one serial loop of the case beside it. It does not measure a failure rate, and it does not reproduce the other work that ran on the host during the two failures; L2 is the heavier load, and it runs outside a gate.
- L5. Inside each gate the case's frame wait is not timed; the timed waits under gate load are L3's.

## 12. Issue text (#1861)

Before G1, a comment:

> **Acceptance evidence plan (2026-11-27, orchestrator, decided by `claude-architect`).** The first criterion is met by two consecutive canonical gates of the same committed head, G1 (`bf-1001-1861`) and G2 (`bf-1001-1861-r2`), both at the wrapper's default of 16 workers, the count at which both failures happened. The recorded extra load beside each gate is row L3: `tests/test_ad1133_live_crew_session_refresh.py::test_owned_replan_current_projection_chain[over-1000-retired]` in a serial loop (`-n 0`, a frame-wait probe loaded) from a separate checkout of that head, started before the gate and stopped after it ends. For each gate this issue gets: the host's `os.cpu_count()`, the gate's start and end UTC, the loop's start and end UTC, each loop run's exit code and frame waits, and the case's outcome in the gate. A gate counts when it completes, the loop covered it with every run passing, and the case passed in it. A gate that aborts before the case runs, or that the loop did not cover, is void: recorded here, not counted, and it does not break the pair. A failure of the case, in a gate or in the loop, stops the item. A gate red only on another test counts for the case; that test is triaged under Gate workers and recorded here. Supplementary rows, run before the gates: L1 (the case 3 times on the base and on the candidate, no added load) and L2 (10 times each, interleaved, under `os.cpu_count()` CPU burners).

After each gate of the head, a comment:

> **Gate `<label>` (<counted / void / red on another test / case failed>).** Head `<sha>`, 16 workers, <start>-<end> UTC, exit <code>; the case <passed / failed / did not run>. Beside it, L3: <start>-<end> UTC, <n> runs, exit codes <list or "all 0">, largest frame wait <x> s; host `os.cpu_count()` <n>. <Other failing tests and where they are triaged, or "none".>

After the merge, tick the four boxes, post this comment, then close #1861 as completed and verify that it is closed:

> Shipped in #<PR> (`<merge sha>`), test only: `tests/test_ad1133_live_crew_session_refresh.py`. `receive_semantic_frame` waits for its first semantic frame until a 15.0 s `time.monotonic()` deadline; `_wait_until` keeps its 500 polls for every caller that passes no deadline. Heartbeat checks (`:2408-2418` on the base) unchanged.
> - Load: G1 `<label>` (<start>-<end> UTC) beside L3 (<n> runs, all passed, largest frame wait <x> s) and G2 `<label>` (<start>-<end> UTC) beside L3 (<n> runs, all passed, largest frame wait <x> s), both of head `<sha>` at 16 workers, the case passed in both; host `os.cpu_count()` <n>. Void or other gates of the head: <list or "none">. Supplementary: L1 <result>; L2 <result>.
> - Bounded failure: `test_receive_semantic_frame_empty_queue_fails_at_its_deadline` (0.05 s deadline inside a 10 s outer bound).
> - Red on the base: AB1 (`..._later_than_500_polls`, a queue that reads empty 501 times).
> - Mutation census: <n> of 12 killed (W1-W12). Gate receipts: `logs/gates/<label>.receipt.json` for each green gate of the head.

## 13. Prior art and blind spots

- Internal: BF-981 part 2 D1 (`DECISIONS.md`:590), "a budget that is not under test is raised far above the start": adopted. The deadline helpers at `test_ad1195_durable_event_seam.py`:247-251 and `issue1375_work_state_bridge.py`:246-251 (a monotonic deadline, the predicate read first): adopted. `test_bf824_pool_health_loop_survives.py`:102-104, "a fixed sleep encodes how fast the box is": the cause stated.
- External: not searched. This is test plumbing with no outside design question; `docs/research/reference-projects.md` not examined for the same reason (considered, deferred: all rows).
- Blind spots: the Windows timer resolution of both `asyncio.sleep` and `time.monotonic` (D5, L3); a heartbeat produced by the hub's own 30 s receive timeout (`ws_event_stream.py`:742-752) could land inside a 15 s wait, and the predicate accepts a well-formed one; `--dist=loadfile` keeps the whole file on one worker, and the change adds about 2.4 s to it.
- Blind spots of the two-gate plan: a 16-worker gate on this host has aborted before (#1523 F-757, addendum of 2026-11-24), and the L3 loop adds load to it (the void rule of 8.5 and its three-gate stop); an L3 run from the gated worktree could change the status the receipt hashes (the separate L3 tree of 8.3); a base merge between G1 and G2 would make them gates of two heads (section 4: nothing is merged between them); the tracker text is committed before the gates, so it cannot carry their result (D10).

## 14. Acceptance criteria

- [ ] AB1 is red on the base and green on the candidate; the focused check of 8.2 passes with the base counts plus 4.
- [ ] L1 and L2 meet section 8.3.
- [ ] G1 and G2 meet section 8.5: two consecutive counted canonical gates of the committed M1 head at 16 workers, the case passed in both, each with an L3 loop that covered the whole gate and whose every run exited 0; each gate's record (8.5 step 2) is posted on #1861; a green receipt of the head exists.
- [ ] W1 to W12 are killed as section 8.4 states.
- [ ] Lines :2408-2418 of the base are unchanged.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle trees (the orchestrator fills this in)
