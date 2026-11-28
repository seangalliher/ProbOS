# BF-987 (#1820, item bf-985 F4): a loop that drains a tracked task set prunes what finished, so it returns when a finished task is still tracked; a census by shape guards the rest

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-19

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-19, amendment A1 (32 pairs, consult session `be9b643a`) after the orchestrator's first-hand oracle run found that a0's census rule flagged a ninth, safe loop (`tests/test_ad1270a_startup_receipts.py:501`); the pairs were applied by the orchestrator.

**Status:** build-ready. Issue #1820. The issue stays open for its other items, and the PR says `Refs #1820`. One BF number. BF-987 is reserved for this repair at `prompts/bf-986-recursion-limit-gc-guard.md:791`, and P1 re-verifies it before the first commit. The number appears only in REPLACE text, new-file text, new-file paths and tracker text, never in a SEARCH.

**Base:** BF-986's branch head `e7c2972c` (`origin/main` `53170fc2` plus BF-986's six commits). BF-986's merge tree equals this tree. BF-986 touches none of the eight files edited here (`git diff --stat 53170fc2 e7c2972c` lists 11 files, none of them in section 7). Build on `origin/main` after BF-986 merges.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`) and the SEARCH blocks are LF. Match and write each file with its own line endings, and write the new file with LF.

**Milestones:**
- M1: the new test file first (red), then the eight loop repairs (green). Tests only, tier LOW, no `src/` line.
- M2: the trackers and the generated ledger pair.

Each milestone is one Builder delegation and one local commit, in order. After M2, run one broad gate: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-987-1820 --receipt logs/gates/bf-987-1820.receipt.json`.

**Captain:** nothing here meets a Captain condition. Only test code and trackers change: no public API, schema, security control, spend or OSS/commercial boundary is involved.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| CPython 3.12's `gather` adds each child that is already done to `done_futs` and then calls `_done_callback` on each synchronously, so with every child done, the outer future is done before it is returned and `await` does not yield | `C:\Users\seang\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\asyncio\tasks.py:826`, `:844`, `:860-861` (3.12.13, the venv base per `d:/ProbOS/.venv/pyvenv.cfg:1,4`) |
| CI runs 3.12, and the stalled worker ran 3.12.16 | `.github/workflows/ci.yml:47`; the dump paths in `faulthandler-gw0.txt` |
| The CI stall: gw0's main thread sat at `tests/test_ad1206_repair_issue.py:62 in drain`, called from `test_ad1207_fault_visibility.py:668 in stop`, `:757 in _replay_context`, `contextlib.py:231 in __aexit__` and `:799 in test_continuous_historical_replay_matches_checked_bridge_wire`. All three 10-minute dumps show it | `ci1834/stacks-1/faulthandler-gw0.txt:41-45`, `:130-134`, `:219-223` |
| The production analogue keeps a task set that only `discard` callbacks empty | `src/probos/runtime.py:1997-1998`, `:2018-2019`; `src/probos/cognitive/turn_promotion.py:2467-2468` (the `hold` set) |
| `asyncio_mode = "auto"`, `timeout = 180`, `addopts = "-n 16 --dist=loadfile"`, `requires-python >= 3.12` | `pyproject.toml:181`, `:190`, `:196`, `:9` |
| A test may import doubles from another test module (the established pattern) | `tests/test_ad1207_fault_visibility.py:587`; `tests/test_ad1323_continue_extension_e2e.py:35` |

## 1. Problem

The loop `while <set>: await asyncio.gather(*tuple(<set>))` relies on each tracked task's `add_done_callback(<set>.discard)` to empty the set.

On the normal path, a task's `discard` runs before the gather's own callback because it was registered first, so the set is empty when the gather returns. If the loop starts while every tracked task is already done and their `discard` callbacks are still queued, the following happens:
- `gather` completes eagerly (section 0).
- The `await` never yields, so the queued callbacks never run.
- The loop spins forever on the event-loop thread.

Because the loop never yields, no `asyncio` timeout (`wait_for`, `asyncio.timeout`) can end it. A cleanup that runs in the same task step as an exception can reach this state. PR #1834 run 44520999819 attempt 1 hit it: shard 1 stalled for 26 minutes until the 38-minute step limit.

Item bf-985 F4 named three such loops. A census by **shape** (section 11, AV1) finds 25 loops in `tests/` whose condition is a container (a `Name` or `Attribute`, or the `BoolOp` of `tests/fixtures/approval_ui_bridge.py:377`) and whose own body awaits `asyncio.gather(...)`. They fall into four groups. A 26th, `while True:` at `tests/test_ad1323_continue_extension_seam.py:187`, drains through a bus and sleeps; its condition is not a container, so it is outside the census.

**Unsafe: eight loops whose body is the gather alone and that prune nothing.**

| # | Site | Container | Users |
|---|---|---|---|
| S1 | `tests/test_ad1206_repair_issue.py:60-62` `_Bus.drain` | `self.tasks` | `test_ad1207_fault_visibility.py:587` (`:668`, `:687`, `:703`, `:729`) |
| S2 | `tests/test_ad1204_approval_resumes_the_turn.py:130-133` `_EventBus.drain` | `self._tasks` | `test_ad1323_continue_extension_e2e.py:35`, `test_ad1323_continue_extension_seam.py:49` |
| S3 | `tests/test_ad1204_approval_resumes_the_turn.py:725-726` (inline) | `hold` | (the test) |
| S4 | `tests/test_ad1204_approval_resumes_the_turn.py:791-792` (inline, the `_boom` exception test) | `hold` | (the test) |
| S5 | `tests/test_bf722_approval_transaction_integrity.py:177-180` `_EventBus.drain` | `self._tasks` | (the file) |
| S6 | `tests/test_bf708_capability_notice.py:244-247` `_RealEmitHost.drain` | `self._event_listener_tasks` (filled by the real `ProbOSRuntime._emit_event_local`) | (the file) |
| S7 | `tests/test_ad1228_standing_interests.py:128-131` `_drain(host)` | `host._event_listener_tasks` | `test_ad1228_standing_interest_e2e.py:32-38` |
| S8 | `tests/test_ad1341_s4_stand_down.py:1275-1276` (inline, in a `finally`) | `agent._promoted_turn_tasks` | (the test at `:1212`) |

**Safe: five loops that prune with `difference_update`.** `test_ad1211_approval_fulfils_every_kind.py:156`, `test_ad1328_s2b_seam_and_wiring.py:248`, `test_ad1328_s2c_park_and_scope.py:252`, `test_ad1328_s2c_resume_seam.py:218`, `test_bf900_dispatch_claim_keeps_the_park.py:233`.

**Safe: one loop that empties its list before the gather.** `tests/test_ad1270a_startup_receipts.py:501-504` (`_close_what_finalization_opened`): `batch = opened[:]`, then `del opened[:]`, then the gather of `batch`. No finished entry stays tracked, so it cannot spin; D4 counts the `del` as a prune.

**Safe: eleven loops that yield after the gather.** These are:
- `tests/fixtures/consulted_evidence_bridge.py:129-131`
- `tests/fixtures/approval_ui_bridge.py:377-380` (its condition is a `BoolOp`, and it sleeps)
- `test_ad1165_turn_promotion.py:135-137`
- `test_ad1208_cost_bounded_turns.py:1467-1469`
- `test_ad1224_durable_tool_start.py:1980-1982`
- `test_ad1226_recall_artifact.py:196-198`
- `test_ad1227_recent_outputs.py:217-219`
- `test_ad1246_long_run_promotion.py:113-115`
- `test_ad1246_long_run_promotion.py:458-464` (the gather sits in a `for` header; an `asyncio.sleep(0)` follows)
- `test_bf705_promotion_deadline.py:119-121`
- `test_issue1417_run_python_child_ownership.py:259-261`

`src/` has no such loop (AV2). Every unsafe site is test code, so the product is unaffected.

## 2. Solution overview

The smallest design:
- Copy the five pruning copies' idiom into the eight unsafe loops, each keeping its own container expression and its `return_exceptions` argument.
- Add one new test file:
  - **T1** runs each importable repaired drain (S1, S2, S5, S6, S7) on its own event loop in a daemon thread, with a finished task tracked, and judges it from the test's thread with `join(5)`. One case drives the real `_Bus.emit` into the exact state the CI stall reached.
  - **T2 and T3** are an AST census. No `while <name or attribute>:` loop in `src/` or `tests/` may have a gather as its only await while pruning nothing (no prune call and no `del` of a subscript). This is the only check that reaches the inline sites (S3, S4, S8) and a ninth copy.

Rejected heavier designs:
- One shared drain helper adopted by all 25 loops: it touches 17 working loops for no defect (considered, deferred).
- A subprocess per mutant with a hard kill: the set-clear stop (section 3, D3) already ends a spinning thread.

## 3. Decisions

- **D1 (scope: eight loops, not three).** The item's census was by name (`while self.tasks:` / `while self._tasks:`). The census by shape finds five more loops with the same defect: S3, S4, S6, S7 and S8. S8 sits in a `finally`, which is the cleanup-after-exception path. Leaving them would leave known stall causes live. This is the same BF, the same defect and the same repair.
- **D2 (the repair).** Use the idiom exactly: `pending = tuple(<c>)`, then `try: await asyncio.gather(*pending[, return_exceptions=True])`, then `finally: <c>.difference_update(task for task in pending if task.done())`.
  - The prune does not depend on callback order, and it also removes a tracked future that has no `discard` callback.
  - Rejected: `await asyncio.sleep(0)` after the gather. It relies on the queued callbacks running in the next pass, and it never removes a done entry that has no callback.
  - Behaviour on the normal path is unchanged: the `discard` of an absent element is a no-op. When the gather raises, the exception still propagates; only the done entries are pruned.
  - **`emit` / `emit_event` and their `add_done_callback(...discard)` stay.** They mirror `ProbOSRuntime._emit_event_local` (`runtime.py:1997-1998`), which the doubles' docstrings say they copy, and they bound the set between drains.
- **D3 (the oracle).** A spin never yields, so `asyncio.wait_for` cannot time it out. pytest-timeout is not usable either:
  - On Windows its thread method ends the process.
  - On Linux its signal method gives one 180 s alarm per test, and that alarm is what the stall's hypothesis says was already spent.

  So each T1 case runs `asyncio.run(...)` in a **daemon thread** and calls `join(5)`. If the thread is still alive, the test **clears the tracked set**. The spinning loop re-reads the set on every pass, so the loop ends, the thread exits, and the test fails with a message that says whether the thread stopped. `tuple(set)` runs in C without releasing the GIL, so a concurrent `clear()` cannot corrupt it.

  Cost:
  - Green: one thread and one new loop per case, a few ms on Windows (Proactor) and Linux.
  - Red: about 5 s per case.

  A thread that the clear could not stop (a mutant that copies the set first) stays a daemon. It shares the GIL in 5 ms slices for the rest of that xdist worker, slowing it without hanging it, and it does not block interpreter exit. The message says so.
- **D4 (the census reverses the earlier rejection of a source scan).** Consult session `c0c04733` rejected a source scan as pinning the defect. This census does not pin a line. It forbids the defect's shape, and it is measured to matter: the census by name found 3 of 8.

  The rule flags a `while` loop when all three of these hold:
  1. its condition is a bare `Name` or `Attribute`, meaning a container's truthiness;
  2. its body, not counting nested function, class or lambda scopes, holds exactly one await-like node (`Await`, `AsyncFor` or `AsyncWith`), and that node is `await <...>.gather(...)` or `await gather(...)`;
  3. its body, not counting nested scopes, prunes nothing: it calls none of `difference_update`, `discard`, `remove` or `clear`, and it holds no `del` statement with a subscript target (`del c[:]`, `del c[k]`). A `del` of a bare name (`del pending`) empties no container and does not count.

  Precision on this tree: P2 (eight hits before the repair, zero after). The `del` clause is what lets `tests/test_ad1270a_startup_receipts.py:501` through: it empties its list with `del opened[:]` before the gather, so no finished entry stays tracked and it cannot spin (a0's rule, without the clause, flagged it as a ninth hit in the oracle's red run). Residuals (register R-1): not detected, a spin through another awaitable that completes eagerly (for example `wait_for` around a gather that is already done) or a loop whose condition is an expression; flagged though safe, a loop that empties its container by rebinding it or with `pop`/`popleft` (none on this tree).
- **D5 (where).** All of it goes in the new file `tests/test_bf987_drain_prunes_finished_tasks.py`. No conftest change and no new fixture module.
- **D6 (deferred).** A shared `drain_tracked` helper for all 25 loops is deferred because it touches working files for no defect.

## 4. Milestones and focused gates

**M1 order:**
1. Write 7.1 alone and run it: **red first** (P2). This run is the campaign of record for rows D-1 to D-8.
2. Apply 7.2 to 7.7.
3. Rerun the focused gate:

`d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf987_drain_prunes_finished_tasks.py tests/test_ad1206_repair_issue.py tests/test_ad1207_fault_visibility.py tests/test_ad1204_approval_resumes_the_turn.py tests/test_ad1323_continue_extension_e2e.py tests/test_ad1323_continue_extension_seam.py tests/test_bf722_approval_transaction_integrity.py tests/test_bf708_capability_notice.py tests/test_ad1228_standing_interests.py tests/test_ad1228_standing_interest_e2e.py tests/test_ad1341_s4_stand_down.py -q -n 0`

The modules that import `_reply` from `test_ad1341_s4_stand_down.py` see no module-level change, so they are not in the gate.

**M2:** after 7.8 and 7.9, run 7.10's generator, `--check`, and `tests/test_ad1184_ad_ledger.py -q -n 0`.

## 5. Consumers of every value this changes

| Changed | Consumer | Expectation |
|---|---|---|
| S1 `_Bus.drain` | `test_ad1207_fault_visibility.py` `_FaultReplay` (`:668`, `:687`, `:703`, `:729`) | Returns as before on the normal path, and returns instead of spinning in the stalled state |
| S2 `_EventBus.drain` | the two AD-1323 files | Same |
| S7 `_drain(host)` | `test_ad1228_standing_interest_e2e.py` | Same signature |
| S3, S4, S8 | their own tests | `hold` is emptied as before |

## 6. Tests (new file `tests/test_bf987_drain_prunes_finished_tasks.py`)

| T | Name | What it proves |
|---|---|---|
| T1 (6 cases) | `test_a_drain_returns_when_a_finished_task_is_still_tracked[ad1206-bus, ad1206-bus-through-emit, ad1204-bus, bf722-bus, bf708-host, ad1228-drain]` | Each repaired drain returns within 5 s with a finished task tracked, and leaves the set empty. The premise (tracked, all done) is asserted before `drain()` starts. `ad1206-bus-through-emit` reaches the CI state through the real `emit` (the listener finishes and its `discard` is still queued) |
| T2 (11 cases) | `test_the_census_flags_exactly_the_loop_that_can_spin[...]` | The detector flags the stalled shape, a bare `gather` with `*list(...)` over an attribute, a prune replaced by `pass`, and a loop whose only `del` is of a name. It ignores an await in a nested scope. It passes the pruning shape, a `del c[:]` before the gather, the yielding shape (a sleep after or before the gather), an `if`, and `while True` |
| T3 | `test_no_loop_in_src_or_tests_awaits_only_an_unpruned_gather` | Zero hits over `src/` and `tests/`. Positive controls, none naming a file: at least one `src/` file and one `tests/` file are scanned, and at least one loop of the shape is let through because it prunes, so a detector that recognises nothing cannot pass. It fails loudly on a parse error |

## 7. The contract

### 7.1 New file: `tests/test_bf987_drain_prunes_finished_tasks.py` (M1)

```python
"""BF-987 (#1820, item bf-985 F4): a loop that drains a tracked task set returns when a finished task is still tracked.

CPython 3.12's ``asyncio.gather`` resolves its outer future at once when every child is already done, and
awaiting a done future does not yield to the event loop. A loop ``while tasks: await asyncio.gather(*tuple(tasks))``
whose set only each task's ``discard`` done-callback empties therefore never ends when it starts with every
tracked task done and those callbacks still queued, and because it never yields, no asyncio timeout can stop it.
CI run 44520999819 stalled a shard for 26 minutes in that loop (``tests/test_ad1206_repair_issue.py:62``).

T1 runs each repaired drain on its own event loop in a daemon thread and judges it from the test's thread with
``join``; on failure it clears the tracked set, which ends a spin, so a regression fails in seconds instead of
hanging the run. T2 and T3 are the census: no ``while`` loop in ``src/`` or ``tests/`` awaits only a ``gather``
over a container it never prunes.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from tests.test_ad1204_approval_resumes_the_turn import _EventBus as _Ad1204Bus
from tests.test_ad1206_repair_issue import _Bus as _Ad1206Bus
from tests.test_ad1228_standing_interests import _drain as _ad1228_drain
from tests.test_ad1228_standing_interests import _EmitHost as _Ad1228Host
from tests.test_bf708_capability_notice import _RealEmitHost as _Bf708Host
from tests.test_bf722_approval_transaction_integrity import _EventBus as _Bf722Bus

_REPO_ROOT = Path(__file__).resolve().parent.parent
_JOIN_S = 5.0  # a repaired drain returns in milliseconds; a spinning one never does
_STOP_S = 5.0
_PRUNE_CALLS = frozenset({"difference_update", "discard", "remove", "clear"})

_Drain = Callable[[], Awaitable[None]]
_Setup = Callable[[set[Any]], Awaitable[None]]
_Case = tuple[set[Any], _Drain, _Setup]


# -- T1: each repaired drain, judged from outside its event loop ---------------


async def _track_a_finished_future(tasks: set[Any]) -> None:
    """A done future with no discard callback: only a prune can remove it."""
    future = asyncio.get_running_loop().create_future()
    future.set_result(None)
    tasks.add(future)


def _ad1206_bus() -> _Case:
    bus = _Ad1206Bus()
    return bus.tasks, bus.drain, _track_a_finished_future


def _ad1206_bus_through_emit() -> _Case:
    """The CI state through the real ``emit``: the listener finished, its discard is still queued."""
    bus = _Ad1206Bus()

    async def _listener(_event: dict[str, Any]) -> None:
        return None

    async def _setup(_tasks: set[Any]) -> None:
        bus.listeners.append(_listener)
        bus.emit("bf987", {})
        await asyncio.sleep(0)  # the listener's task finishes in this pass; its discard runs in the next

    return bus.tasks, bus.drain, _setup


def _ad1204_bus() -> _Case:
    bus = _Ad1204Bus()
    return bus._tasks, bus.drain, _track_a_finished_future


def _bf722_bus() -> _Case:
    bus = _Bf722Bus()
    return bus._tasks, bus.drain, _track_a_finished_future


def _bf708_host() -> _Case:
    host = _Bf708Host(None)
    return host._event_listener_tasks, host.drain, _track_a_finished_future


def _ad1228_drain_case() -> _Case:
    host = _Ad1228Host()

    async def _drain() -> None:
        await _ad1228_drain(host)

    return host._event_listener_tasks, _drain, _track_a_finished_future


def _drain_in_own_loop(tasks: set[Any], drain: _Drain, setup: _Setup) -> None:
    outcome: dict[str, Any] = {}

    async def _main() -> None:
        await setup(tasks)
        assert tasks, "premise: a task is tracked when drain starts"
        assert all(task.done() for task in tasks), "premise: every tracked task is done when drain starts"
        outcome["premise"] = True
        await drain()

    def _target() -> None:
        try:
            asyncio.run(_main())
        except BaseException as exc:  # re-raised on the test's thread below
            outcome["error"] = exc
        else:
            outcome["returned"] = True

    thread = threading.Thread(target=_target, name="bf987-drain", daemon=True)
    thread.start()
    thread.join(_JOIN_S)
    if thread.is_alive():
        tasks.clear()  # the loop re-reads the set on every pass, so this ends a spin and the thread with it
        thread.join(_STOP_S)
        state = (
            "still spinning after the set was cleared; it stays a daemon thread until this worker exits"
            if thread.is_alive() else "stopped by clearing the set"
        )
        pytest.fail(f"drain did not return within {_JOIN_S:.0f} s with a finished task still tracked ({state})")
    if "error" in outcome:
        raise outcome["error"]
    assert outcome.get("premise") is True and outcome.get("returned") is True
    assert not tasks, "drain returned but left a finished task tracked"


@pytest.mark.parametrize("case", [
    pytest.param(_ad1206_bus, id="ad1206-bus"),
    pytest.param(_ad1206_bus_through_emit, id="ad1206-bus-through-emit"),
    pytest.param(_ad1204_bus, id="ad1204-bus"),
    pytest.param(_bf722_bus, id="bf722-bus"),
    pytest.param(_bf708_host, id="bf708-host"),
    pytest.param(_ad1228_drain_case, id="ad1228-drain"),
])
def test_a_drain_returns_when_a_finished_task_is_still_tracked(case: Callable[[], _Case]) -> None:
    tasks, drain, setup = case()
    _drain_in_own_loop(tasks, drain, setup)


# -- T2, T3: the census by shape -----------------------------------------------


def _is_gather(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Await) and isinstance(node.value, ast.Call)):
        return False
    func = node.value.func
    return (isinstance(func, ast.Attribute) and func.attr == "gather") or (
        isinstance(func, ast.Name) and func.id == "gather"
    )


def _awaits_and_prunes(body: list[ast.stmt]) -> tuple[list[ast.AST], bool]:
    awaits: list[ast.AST] = []
    prunes = False
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue  # a nested scope's awaits do not run in this loop's pass
        if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            awaits.append(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _PRUNE_CALLS:
            prunes = True
        elif isinstance(node, ast.Delete) and any(isinstance(target, ast.Subscript) for target in node.targets):
            prunes = True  # ``del c[:]`` empties the container, as a prune call does; ``del name`` does not
        stack.extend(ast.iter_child_nodes(node))
    return awaits, prunes


def _census(source: str) -> tuple[list[int], int]:
    """Lines of ``while <container>:`` loops whose only await is a ``gather`` and that prune nothing, and the
    number of loops of that shape that a prune lets through (T3's positive control)."""
    hits: list[int] = []
    pruned = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.While) or not isinstance(node.test, (ast.Name, ast.Attribute)):
            continue
        awaits, prunes = _awaits_and_prunes(node.body)
        if len(awaits) == 1 and _is_gather(awaits[0]):
            if prunes:
                pruned += 1
            else:
                hits.append(node.lineno)
    return sorted(hits), pruned


def _spin_loops(source: str) -> list[int]:
    """Lines of ``while <container>:`` loops whose only await is a ``gather`` and that prune nothing."""
    return _census(source)[0]


_HEAD = "async def _f(tasks, host):\n"


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param(_HEAD + "    while tasks:\n        await asyncio.gather(*tuple(tasks))\n", [2], id="the-stalled-shape"),
    pytest.param(
        _HEAD + "    while host.tasks:\n        await gather(*list(host.tasks), return_exceptions=True)\n",
        [2], id="attribute-list-bare-gather",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        pending = tuple(tasks)\n        try:\n"
        "            await asyncio.gather(*pending)\n        finally:\n            pass\n",
        [2], id="prune-removed",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        async def _inner():\n            await asyncio.sleep(0)\n"
        "        await asyncio.gather(*tuple(tasks))\n",
        [2], id="nested-scope-await-does-not-count",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        pending = tuple(tasks)\n        try:\n"
        "            await asyncio.gather(*pending)\n        finally:\n"
        "            tasks.difference_update(t for t in pending if t.done())\n",
        [], id="pruned",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        await asyncio.gather(*tuple(tasks))\n        await asyncio.sleep(0)\n",
        [], id="yields",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        await asyncio.sleep(0)\n        await asyncio.gather(*tuple(tasks))\n",
        [], id="yields-before-the-gather",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        batch = tasks[:]\n        del tasks[:]\n"
        "        await asyncio.gather(*batch, return_exceptions=True)\n",
        [], id="del-prunes-the-container",
    ),
    pytest.param(
        _HEAD + "    while tasks:\n        pending = tuple(tasks)\n        await asyncio.gather(*pending)\n"
        "        del pending\n",
        [2], id="del-of-a-name-does-not-prune",
    ),
    pytest.param(_HEAD + "    if tasks:\n        await asyncio.gather(*tasks)\n", [], id="not-a-loop"),
    pytest.param(
        _HEAD + "    while True:\n        await asyncio.gather(*tuple(tasks))\n        break\n",
        [], id="condition-not-a-container",
    ),
])
def test_the_census_flags_exactly_the_loop_that_can_spin(source: str, expected: list[int]) -> None:
    assert _spin_loops(source) == expected


def test_no_loop_in_src_or_tests_awaits_only_an_unpruned_gather() -> None:
    scanned: list[str] = []
    hits: list[str] = []
    let_through = 0
    for top in ("src", "tests"):
        for path in sorted((_REPO_ROOT / top).rglob("*.py")):
            text = path.read_text(encoding="utf-8-sig")
            if "gather(" not in text:
                continue
            name = path.relative_to(_REPO_ROOT).as_posix()
            scanned.append(name)
            try:
                lines, pruned = _census(text)
            except SyntaxError as exc:
                pytest.fail(f"{name} does not parse, so the census cannot read it: {exc}")
            hits.extend(f"{name}:{line}" for line in lines)
            let_through += pruned
    # Positive controls, naming no file so a rename cannot fail this test: the scan reached both trees, and it
    # recognised at least one loop of the shape that a prune lets through, so a detector that sees nothing fails.
    assert any(name.startswith("src/") for name in scanned), "the census scanned no src/ file"
    assert any(name.startswith("tests/") for name in scanned), "the census scanned no tests/ file"
    assert let_through >= 1, "the census recognised no pruning drain loop, so its zero hits prove nothing"
    assert hits == [], (
        "a while loop whose only await is asyncio.gather over a set it never prunes spins forever once every "
        "tracked task is done (BF-987); prune with difference_update as tests/test_ad1211_approval_fulfils_every_kind.py "
        "does: " + ", ".join(hits)
    )
```

### 7.2 `tests/test_ad1206_repair_issue.py` (M1, S1)

SEARCH:
```python
            task = asyncio.create_task(listener({"type": kind, "data": data}))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def drain(self):
        while self.tasks:
            await asyncio.gather(*tuple(self.tasks))
```
REPLACE:
```python
            task = asyncio.create_task(listener({"type": kind, "data": data}))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def drain(self):
        while self.tasks:
            pending = tuple(self.tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self.tasks.difference_update(task for task in pending if task.done())
```

### 7.3 `tests/test_ad1204_approval_resumes_the_turn.py` (M1, S2, S3, S4, in file order)

SEARCH:
```python
    def emit_event(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = getattr(event_type, "value", event_type)
        self.emitted.append(str(type_str))
        event = {
            "type": str(type_str),
            "data": dict(data or {}),
            "timestamp": time.time(),
        }
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))
```
REPLACE:
```python
    def emit_event(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = getattr(event_type, "value", event_type)
        self.emitted.append(str(type_str))
        event = {
            "type": str(type_str),
            "data": dict(data or {}),
            "timestamp": time.time(),
        }
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            pending = tuple(self._tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self._tasks.difference_update(task for task in pending if task.done())
```

SEARCH:
```python
            on_promoted=seen.append,
        )
        release.set()
        while hold:
            await asyncio.gather(*tuple(hold), return_exceptions=True)
```
REPLACE:
```python
            on_promoted=seen.append,
        )
        release.set()
        while hold:
            pending = tuple(hold)
            try:
                await asyncio.gather(*pending, return_exceptions=True)
            finally:
                hold.difference_update(task for task in pending if task.done())
```

SEARCH:
```python
            on_promoted=_boom,
        )
        release.set()
        while hold:
            await asyncio.gather(*tuple(hold), return_exceptions=True)
```
REPLACE:
```python
            on_promoted=_boom,
        )
        release.set()
        while hold:
            pending = tuple(hold)
            try:
                await asyncio.gather(*pending, return_exceptions=True)
            finally:
                hold.difference_update(task for task in pending if task.done())
```

### 7.4 `tests/test_bf722_approval_transaction_integrity.py` (M1, S5)

SEARCH:
```python
    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        self.emitted.append(type_str)
        event = {
            "type": type_str,
            "data": dict(data or {}),
            "timestamp": time.time(),
        }
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))
```
REPLACE:
```python
    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        self.emitted.append(type_str)
        event = {
            "type": type_str,
            "data": dict(data or {}),
            "timestamp": time.time(),
        }
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            pending = tuple(self._tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self._tasks.difference_update(task for task in pending if task.done())
```

### 7.5 `tests/test_bf708_capability_notice.py` (M1, S6)

SEARCH:
```python
        self._event_listener_tasks: set[asyncio.Task] = set()
        self._nats_events_wired = False

    async def drain(self) -> None:
        """Await the listener tasks ``_emit_event_local`` spawned."""
        while self._event_listener_tasks:
            await asyncio.gather(*tuple(self._event_listener_tasks))
```
REPLACE:
```python
        self._event_listener_tasks: set[asyncio.Task] = set()
        self._nats_events_wired = False

    async def drain(self) -> None:
        """Await the listener tasks ``_emit_event_local`` spawned."""
        while self._event_listener_tasks:
            pending = tuple(self._event_listener_tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self._event_listener_tasks.difference_update(task for task in pending if task.done())
```

### 7.6 `tests/test_ad1228_standing_interests.py` (M1, S7)

SEARCH:
```python
async def _drain(host: _EmitHost) -> None:
    """Await every coroutine-listener task the host started (never a sleep)."""
    while host._event_listener_tasks:
        await asyncio.gather(*list(host._event_listener_tasks))
```
REPLACE:
```python
async def _drain(host: _EmitHost) -> None:
    """Await every coroutine-listener task the host started (never a sleep)."""
    while host._event_listener_tasks:
        pending = tuple(host._event_listener_tasks)
        try:
            await asyncio.gather(*pending)
        finally:
            host._event_listener_tasks.difference_update(task for task in pending if task.done())
```

### 7.7 `tests/test_ad1341_s4_stand_down.py` (M1, S8)

SEARCH:
```python
    finally:
        for agent in agents:
            while agent._promoted_turn_tasks:
                await asyncio.gather(*tuple(agent._promoted_turn_tasks), return_exceptions=True)
        await work.stop()
```
REPLACE:
```python
    finally:
        for agent in agents:
            while agent._promoted_turn_tasks:
                pending = tuple(agent._promoted_turn_tasks)
                try:
                    await asyncio.gather(*pending, return_exceptions=True)
                finally:
                    agent._promoted_turn_tasks.difference_update(task for task in pending if task.done())
        await work.stop()
```

### 7.8 `PROGRESS.md` (M2)

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-987 (2026-11-19), #1820 bf-985 F4 -- a loop that drains a tracked task set prunes what finished, so it returns when a finished task is still tracked.** CPython 3.12's `asyncio.gather` completes without yielding when every child is already done, so `while tasks: await asyncio.gather(*tuple(tasks))` spun forever on the event-loop thread when it started with a finished task whose `discard` callback was still queued, and no asyncio timeout can end a loop that never yields. BF-985's stack dumps caught it on their first stall (PR #1834, run 44520999819 attempt 1): shard 1's gw0 sat 26 minutes at `tests/test_ad1206_repair_issue.py:62`. The prune idiom that five copies already carried (`pending = tuple(...)`, the gather, `finally: difference_update` of the done ones) now ends the eight loops that lacked it: the `drain` helpers in `test_ad1206_repair_issue.py` (used by `test_ad1207_fault_visibility.py`), `test_ad1204_approval_resumes_the_turn.py` (used by the two AD-1323 files), `test_bf722_approval_transaction_integrity.py` and `test_bf708_capability_notice.py`; `_drain` in `test_ad1228_standing_interests.py`; and three inline loops (two in `test_ad1204_approval_resumes_the_turn.py`, one in a `finally` of `test_ad1341_s4_stand_down.py`). The item named three; a census by shape rather than by name found eight. New `tests/test_bf987_drain_prunes_finished_tasks.py`: each repaired helper runs on its own loop in a daemon thread and must return within 5 s with a finished task tracked (one case drives the real `emit` into the CI state), and an AST census fails on any `while` loop in `src/` or `tests/` whose only await is a `gather` over a container it never prunes. This corrects BF-985's entry (2026-11-19), whose "The cause of the stall is still unknown" no longer holds for run 44520999819: that stall's cause is this loop. Whether the three earlier stalls (runs 36907487200, 41764125537 and 44395509240), which left no stack, had the same cause is unknown, and so is what raised first in the stalled test. Contract `prompts/bf-987-drain-prunes-finished-tasks.md`.
```

### 7.9 `DECISIONS.md` (M2)

SEARCH:
```markdown
### BF-986 -- #1754 GATE-F1: a test at the recursion limit runs with the collector quiet; the census of loop leakers runs once (2026-11-19, #1754)
```
REPLACE:
```markdown
### BF-987 -- #1820 bf-985 F4: a loop that drains a tracked task set prunes what finished; a census by shape guards the rest (2026-11-19, #1820)

- *Mechanism.* CPython 3.12's `asyncio.gather` resolves its outer future synchronously when every child is already done (`asyncio/tasks.py`, the `done_futs` pass), and awaiting a done future does not yield. A loop `while tasks: await asyncio.gather(*tuple(tasks))`, whose set only `discard` done-callbacks empty, spins forever on the event-loop thread if it starts while every tracked task is done and their callbacks are still queued; no asyncio timeout can end it. BF-985's dumps found it on their first stall (run 44520999819 attempt 1, gw0 at `tests/test_ad1206_repair_issue.py:62`).
- *Repair.* The idiom of the five copies that already prune, in the eight loops that lacked it (S1 to S8 of the contract). Each keeps its own container and its `return_exceptions`. `emit`'s `add_done_callback(discard)` stays: it mirrors `ProbOSRuntime._emit_event_local` and bounds the set between drains. Rejected: `await asyncio.sleep(0)` after the gather, because it relies on the queued callbacks running in the next pass and never removes a tracked future that has no callback. The seventeen loops that already prune (five with `difference_update`, one that empties its list with `del` before the gather) or yield (eleven) are unchanged.
- *Oracle.* A drain that spins never yields, so `asyncio.wait_for` cannot time it out, and pytest-timeout ends the process on Windows. Each case runs `asyncio.run` in a daemon thread and is judged by `join(5)`; on failure the test clears the tracked set, which ends the spin, so a regression fails in about 5 s and leaves no thread running.
- *Census.* An AST check over `src/` and `tests/`: no `while <name or attribute>:` loop whose only await is a `gather` and whose body neither calls a prune method nor deletes a subscript (`del c[:]`). It reverses consult `c0c04733`'s rejection of a source scan, because it forbids the defect's shape rather than pinning a line, and a census by helper name had found three of the eight. Not detected: a spin through another awaitable that completes eagerly (for example `wait_for` around a gather that is already done) or a loop whose condition is an expression.
- *Correction.* BF-985's entry ("*Residual.* The stall's cause stays unknown until the first stall's `ci-shard-stacks-K` is read") is superseded for run 44520999819: its cause is this loop. Whether the three earlier stalls had it is unknown (they left no stacks). What raised first in that test is unknown. The hypothesis that the body's `drain` (`test_ad1207_fault_visibility.py:687`) spun first, was ended by pytest-timeout's 180 s alarm, and that the cleanup's `drain` then spun with no alarm left, is unverified. BF-985's entry is not edited.
- *Deferred.* One shared drain helper for every copy (it touches working loops for no defect).
- *Reversal.* Revert the commits: the eight loops can spin again and the census goes.

### BF-986 -- #1754 GATE-F1: a test at the recursion limit runs with the collector quiet; the census of loop leakers runs once (2026-11-19, #1754)
```

### 7.10 Generated: the ledger pair (M2)

After 7.8 and 7.9, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, which go in M2's commit; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`. The date of the tracker entries is 2026-11-19. **`roadmap.md`:** no row, because the Bug Tracker lists only bugs deliberately not fixed.

## 8. Issue closure (the orchestrator posts these; nothing here edits GitHub)

### 8.1 Tick on #1820: bf-985 F4
Change `- [ ] **bf-985 F4 (P3, Low;` to `- [x] **bf-985 F4 (P3, Low;` and append to the end of the item:
` **Fixed (BF-987, PR #...):** the prune idiom in the eight loops that lacked it: the three named here, plus \`test_bf708_capability_notice.py:244\`, \`test_ad1228_standing_interests.py:128\`, two inline loops in \`test_ad1204_approval_resumes_the_turn.py\` (\`:725\`, \`:791\`) and one in a \`finally\` of \`test_ad1341_s4_stand_down.py:1275\`, found by a census by shape. \`tests/test_bf987_drain_prunes_finished_tasks.py\` judges each helper from outside its event loop and fails on any new unpruned loop. What raised first in the stalled test stays unknown.`

### 8.2 Sub-bullet under bf-983 F2 (tick it)
`- [x] **Cause located for one occurrence (BF-987, PR #...):** run 44520999819 attempt 1 stalled in an unpruned drain loop (bf-985 F4), now repaired together with the seven other loops like it. The three earlier stalls (runs 36907487200, 41764125537, 44395509240) left no stack, so whether they had this cause is unknown. A stall of another cause still writes its dumps (BF-985).`

### 8.3 Comment on #1820 (at merge)
> bf-985 F4 fixed by BF-987 (PR #...). Python 3.12's `asyncio.gather` returns without yielding when every child is already done, so a drain loop that relies on `discard` callbacks spins forever if it starts with only finished tasks tracked. That is what held shard 1 of run 44520999819 for 26 minutes. The item named three loops, and a census by shape found eight. All eight now prune what finished, as five other copies already did. The new test runs each helper on its own loop in a thread and judges it by `join(5)`, and an AST census fails on any new unpruned loop in `src/` or `tests/`. Not shown by this PR: whether the three earlier stalls had this cause, and what raised first in the stalled test. Only later CI runs can show that this stall no longer occurs; a stall of another cause still writes dumps (BF-985).

## 9. What this does NOT change

- No `src/` file, config, `EventType`, route, table or flag. `pyproject.toml` is unchanged.
- The seventeen loops that already prune or yield (section 1), the `emit` / `emit_event` methods, `add_done_callback(...discard)`, and every other line of the six edited test files.
- `tests/conftest.py`, BF-985's watchdog and plugin, and BF-986's guard.
- BF-985's PROGRESS and DECISIONS entries. They are corrected in words by the new entries and are not edited.

## 10. Mutation rows (one campaign; restore between rows; run only the listed killers)

Rows D-1 to D-8 are the **base state**. The red-first run of P2 (7.1 added, 7.2 to 7.7 not yet applied) is their campaign of record. Record the base tree and the sha256 of each of the six edited files. On a later tree whose files match, do not rerun these rows; rerun a row only if its file differs.

| # | M | Site | Mutate to | Killed by |
|---|---|---|---|---|
| D-1 | M1 | S1 `_Bus.drain` | the two-line `while self.tasks: await asyncio.gather(*tuple(self.tasks))` | T1[ad1206-bus], T1[ad1206-bus-through-emit], T3 |
| D-2 | M1 | S2 | the original two lines | T1[ad1204-bus], T3 |
| D-3 | M1 | S3 | the original two lines | T3 |
| D-4 | M1 | S4 | the original two lines | T3 |
| D-5 | M1 | S5 | the original two lines | T1[bf722-bus], T3 |
| D-6 | M1 | S6 | the original two lines | T1[bf708-host], T3 |
| D-7 | M1 | S7 | the original two lines | T1[ad1228-drain], T3 |
| D-8 | M1 | S8 | the original two lines | T3 |
| P-1 | M1 | S1: `self.tasks.difference_update(task for task in pending if task.done())` | `pass` | T1[ad1206-bus], T1[ad1206-bus-through-emit], T3 |
| P-2 | M1 | S8: `agent._promoted_turn_tasks.difference_update(task for task in pending if task.done())` | `pass` | T3 |
| C-1 | M1 | 7.1: `if not isinstance(node, ast.While) or not isinstance(node.test, (ast.Name, ast.Attribute)):` | `if not isinstance(node, ast.While):` | T2[condition-not-a-container] |
| C-2 | M1 | 7.1: `if len(awaits) == 1 and _is_gather(awaits[0]):` | `if _is_gather(awaits[0]):` | T2[yields-before-the-gather]; T3 (an `IndexError` on a `while` with no await, such as `while stack:` in this file). T2[yields] does not kill it: the traversal pops the last statement first, so `awaits[0]` is the sleep |
| C-3 | M1 | 7.1: `continue  # a nested scope's awaits do not run in this loop's pass` | `pass` | T2[nested-scope-await-does-not-count] |
| C-4 | M1 | 7.1: `_PRUNE_CALLS = frozenset({"difference_update", "discard", "remove", "clear"})` | `_PRUNE_CALLS = frozenset()` | T2[pruned], T3 |
| C-5 | M1 | 7.1: `return (isinstance(func, ast.Attribute) and func.attr == "gather") or (` (the whole expression) | `return False` | T2[the-stalled-shape], T2[attribute-list-bare-gather], T2[prune-removed], T2[nested-scope-await-does-not-count], T2[del-of-a-name-does-not-prune], T3 (the `let_through >= 1` control) |
| C-6 | M1 | 7.1: `for top in ("src", "tests"):` | `for top in ("src",):` | T3 (the `tests/` control) |
| C-7 | M1 | 7.1: `elif isinstance(node, ast.Delete) and any(isinstance(target, ast.Subscript) for target in node.targets):` | `elif False:` | T2[del-prunes-the-container], T3 (flags `tests/test_ad1270a_startup_receipts.py:501`) |
| C-8 | M1 | 7.1: the same line as C-7 | `elif isinstance(node, ast.Delete):` | T2[del-of-a-name-does-not-prune] |
| C-9 | M1 | 7.1: `let_through += pruned` | `let_through += 0` | T3 (the `let_through >= 1` control) |

**Unchanged-file check:** this must print nothing and exit 0.

`git diff --exit-code <base> HEAD -- tests/test_ad1211_approval_fulfils_every_kind.py tests/test_ad1328_s2b_seam_and_wiring.py tests/test_ad1328_s2c_park_and_scope.py tests/test_ad1328_s2c_resume_seam.py tests/test_bf900_dispatch_claim_keeps_the_park.py tests/fixtures/consulted_evidence_bridge.py tests/fixtures/approval_ui_bridge.py tests/test_ad1165_turn_promotion.py tests/test_ad1208_cost_bounded_turns.py tests/test_ad1224_durable_tool_start.py tests/test_ad1226_recall_artifact.py tests/test_ad1227_recent_outputs.py tests/test_ad1246_long_run_promotion.py tests/test_bf705_promotion_deadline.py tests/test_issue1417_run_python_child_ownership.py tests/test_ad1270a_startup_receipts.py`

Also check that `git diff --stat <base> HEAD` lists exactly: the six edited test files, the new test file, `PROGRESS.md`, `DECISIONS.md` and the ledger pair, plus this prompt.

## 11. Verified Against Codebase (2026-11-19, `e7c2972c`; BF-986's merge tree equals this tree)

```
rg -n "while self\.\w+:|gather\(\*tuple\(self\.|gather\(\*self\." tests   (positive control: the CI helper is found)
  tests/test_ad1206_repair_issue.py:61:        while self.tasks:
  tests/test_ad1206_repair_issue.py:62:            await asyncio.gather(*tuple(self.tasks))
  tests/test_ad1204_approval_resumes_the_turn.py:132-133, tests/test_bf722_approval_transaction_integrity.py:179-180,
  tests/test_bf708_capability_notice.py:246-247, tests/fixtures/consulted_evidence_bridge.py:129-130,
  tests/fixtures/approval_ui_bridge.py:379, pruned: test_ad1211...:156, test_ad1328_s2b...:248,
  test_ad1328_s2c_park...:252, test_ad1328_s2c_resume...:218, test_bf900...:233
tests/test_ad1206_repair_issue.py:46 class _Bus: ; :49 self.tasks = set() ; :58 task.add_done_callback(self.tasks.discard) ; :60 async def drain(self):
tests/test_ad1204_approval_resumes_the_turn.py:100 class _EventBus: ; :111 self._tasks ; :117 def emit_event( ; :128 add_done_callback(self._tasks.discard)
  :130-133 drain ; :722 on_promoted=seen.append, ; :724-726 release.set() / while hold: / gather ; :788 on_promoted=_boom, ; :790-792
tests/test_bf722_approval_transaction_integrity.py:145 class _EventBus: ; :158 self._tasks ; :164 def emit( ; :175 ; :177-180 drain
tests/test_bf708_capability_notice.py:220 class _RealEmitHost: ; :232 _emit_event_local = ProbOSRuntime._emit_event_local ; :235 def __init__(self, ward_room: Any) ; :241 ; :244-247 drain
tests/test_ad1228_standing_interests.py:109 class _EmitHost: ; :116 _emit_event_local = ProbOSRuntime._emit_event_local ; :119 def __init__(self) ; :122 ; :128-131 _drain
tests/test_ad1228_standing_interest_e2e.py:32-38 from tests.test_ad1228_standing_interests import (... _drain, _EmitHost,)
tests/test_ad1341_s4_stand_down.py:1212 async def test_a_stand_down_turn_is_answered_inline_by_the_real_dm_consumer_and_never_promoted ; :1273-1277 finally / for agent / while / gather / await work.stop()
tests/test_ad1207_fault_visibility.py:587 from tests.test_ad1206_repair_issue import _Bus, _Credentials, _HTTP ; :666-668 stop -> release.set(); await self.bus.drain() ; :687 ; :703 ; :729 ; :744-757 _replay_context finally: await replay.stop()
tests/test_ad1323_continue_extension_e2e.py:35, tests/test_ad1323_continue_extension_seam.py:49 from tests.test_ad1204_approval_resumes_the_turn import _EventBus, _RecordingRouter
rg -n "\bpending\b" over the six edited files: no use inside the test functions at ad1204:700-800 or ad1341:1212-1280 (no shadowing)
src/probos/runtime.py:1997-1998, :2018-2019 add / add_done_callback(self._event_listener_tasks.discard)
src/probos/cognitive/turn_promotion.py:2467-2468 hold.add(task) / task.add_done_callback(hold.discard)
tests/test_ad1270a_startup_receipts.py:491 async def _close_what_finalization_opened ; :501 while opened: ; :502 batch = opened[:] ; :503 del opened[:] ; :504 await asyncio.gather(*(connection.close() for connection in batch), return_exceptions=True)
tests/test_ad1246_long_run_promotion.py:458 while tasks: ; :459 for outcome in await asyncio.gather(*tuple(tasks), return_exceptions=True): ; :464 await asyncio.sleep(0)
tests/test_ad1323_continue_extension_seam.py:187 while True: ; :188 await ship.bus.drain()
<uv cpython-3.12>/Lib/asyncio/tasks.py:826 done_futs = [] ; :844 done_futs.append(fut) ; :860-861 for fut in done_futs: _done_callback(fut)
pyproject.toml:9 requires-python ; :181 asyncio_mode = "auto" ; :190 timeout = 180 ; :196 addopts = "-n 16 --dist=loadfile"
.github/workflows/ci.yml:47 python-version: '3.12'
faulthandler-gw0.txt:41-45 (and :130-134, :219-223) drain <- stop <- _replay_context <- __aexit__ <- test_continuous_historical_replay...
PROGRESS.md:1 # ProbOS Progress ; :8 "The cause of the stall is still unknown: the next stall's artifact names it"
DECISIONS.md:1703 ### BF-986 -- ... (2026-11-19, #1754) ; :1719 ### BF-985 -- ... ; :1730 *Residual.* The stall's cause stays unknown until the first stall's `ci-shard-stacks-K` is read.
docs/development/open-ads-report.md:32 | BF | **BF-986** | **BF-987** | BF-986 | _(none)_ |
prompts/bf-986-recursion-limit-gc-guard.md:791 "BF-987 is reserved by the orchestrator for the repair of item bf-985 F4 of #1820"
git diff --stat 53170fc2 e7c2972c: 11 files, none of the eight edited here
tests/__init__.py, tests/fixtures/__init__.py, scripts/gen_ad_ledger.py, tests/test_ad1184_ad_ledger.py, scripts/run_test_gate.py exist
```

## Absence Verified (2026-11-19)

| | CLAIM | RUN | FOUND | HOLDS |
|---|---|---|---|---|
| AV1 | Exactly eight spin-shaped loops in `tests/` | the orchestrator's AST census (2026-11-19, BF-986's merge tree): every `while` whose own-scope body awaits a gather, over `src/` and `tests/`; premises asserted: the CI helper is found, `src/` is scanned, every file that contains `gather(` parses. a0's two multiline `rg` searches missed loops with two or more lines between the `while` and the gather | `tests/`: 26 loops. 9 meet conditions 1 and 2 with no prune call: S1 to S8, plus `test_ad1270a_startup_receipts.py:501`, which empties its list with `del opened[:]` before the gather and cannot spin. 5 prune with `difference_update`. 11 have a container condition (`Name`, `Attribute` or `BoolOp`) and yield. 1 `while True:` sleeps (`test_ad1323_continue_extension_seam.py:187`). `src/`: 6 loops, none of the shape (3 sleep; 3 have a `Constant`, `UnaryOp` or `Compare` condition). No `while` with `wait_for(asyncio.gather` or `shield(asyncio.gather` as its body (`rg` over `src` and `tests`) | yes, with D4's `del` clause; T3 re-asserts it by AST (P2) |
| AV2 | No such loop in `src/` | the same two searches over `src`, plus `rg 'while [^\n]*:\s*\n[^\n]*\n?[^\n]*asyncio\.(gather\|wait)\(' src` | only `while not x.done(): await asyncio.wait(...)` loops (`attachments/filesystem_store.py:63`, `doctor/checks/llm_check.py:349`, `perception/consumer.py:805`, `identity_writer.py:143`), none of the shape | yes |
| AV3 | BF-987 is free | `git log --all --format=%s -i --grep="BF-98[4-9]"`; Glob `prompts/bf-98*.md`; `gh issue list --state all --search "BF-987 in:title"`; `rg BF-987` | no subject (commit subjects carry no BF number), highest prompt `bf-986`, no issue; the text appears only in the ledger row and the BF-986 reservation | yes |
| AV4 | The two `if`-guarded gathers are not loops | `rg -B3 'await asyncio.gather\(\*(self\.)?tasks\)' tests/test_ad1128_crew_session_ingress_dedup.py`; `rg -B5` at `test_ad1224_durable_tool_start.py:754` | `if self.tasks:` (`:327`, `:378`); `if self._nats_publish_tasks:` (`:753`) | yes |

## 12. Deterministic checks, resolved up front

- 3.12's eager `gather` path is in the local stdlib (section 0). CI's 3.12.16 shows the same frame in the stall.
- `asyncio.run` in a non-main thread installs no signal handler on Windows or Linux, and the new loop is the policy default (Proactor on Windows).
- `tuple(set)` and `set.clear()` are C calls that hold the GIL, so the cross-thread clear in T1 is safe.
- In the T1 cases, no double is bound to a loop at construction (`_Bus()`, `_EventBus()`, `_RealEmitHost(None)`, `_EmitHost()` only build lists and sets). Futures are created inside the thread's loop.
- pytest-timeout (180 s) does not take part: green cases take milliseconds and a red case about 5 to 10 s.
- `ast.parse` accepts the T2 sources (the awaits sit inside `async def _f`).

## 13. Prior art and blind spots

- **Prior art in the repo:** the prune idiom first appears in `4b7dfb3b` (2026-09-17) and is copied in five files (adopted as is). The eleven loops that yield are the alternative, rejected in D2. The one loop that empties its list with `del opened[:]` before the gather (`test_ad1270a_startup_receipts.py:501`) works only on a list, not on the sets the eight loops drain; not adopted.
- **External:** this is test-helper plumbing with no outside design analogue, so no web search was made. The fact it depends on is CPython's `gather`, read from the 3.12.13 source; it was not checked against 3.11 or 3.13.
- **Blind spots, recorded rather than worked:**
  - a spin through another eagerly completing await (`wait_for` around a gather that is already done, `asyncio.timeout` + gather) -- register R-1;
  - an expression condition (`while a or b:`) -- R-1;
  - what raised first in the CI test -- R-2;
  - whether the three earlier stalls share this cause -- R-3.

## 14. Diff Reviewer: properties to verify

1. Each of S1 to S8 has exactly the five-line idiom over its own container: `pending = tuple(<c>)`, the gather of `*pending` (with `return_exceptions=True` exactly where it was before), and `finally:` `<c>.difference_update(task for task in pending if task.done())`. No other line in those six files changes.
2. Every `emit` / `emit_event` and every `add_done_callback(...discard)` is byte-identical.
3. The seventeen loops that already prune or yield are untouched (the section 10 command).
4. T1 judges from outside the loop (`threading.Thread(daemon=True)` plus `join`) and never through `wait_for` or pytest-timeout.
5. On failure, T1 clears the set before failing and reports whether the thread stopped. An exception raised in the thread is re-raised on the test's thread. The premise is asserted before `drain()`, and an empty set is asserted after it.
6. The census flags only per the three conditions of D4. Nested scopes are excluded. A `del` counts as a prune only with a subscript target. It scans `src/` and `tests/`, has three positive controls that name no file (a `src/` file and a `tests/` file are scanned, and at least one loop of the shape is let through by a prune), and a parse error fails the test by name.
7. No `src/`, `pyproject.toml` or conftest change. One PROGRESS entry and one DECISIONS entry are added, BF-985's entries are not edited, and the ledger pair is generated.

## 15. Acceptance criteria

1. Each importable repaired drain returns within 5 s with a finished task tracked, including through the real `emit` (T1).
2. No `while` loop in `src/` or `tests/` awaits only an unpruned `gather` (T3), and the detector is exact on its eleven cases (T2).
3. Every section 10 row is killed by its named tests, and D-1 to D-8 were recorded red-first (P2).
4. The seventeen loops that already prune or yield are unchanged, and the consumers in section 4 pass.
5. The PROGRESS and DECISIONS entries correct BF-985's "unknown" statement in words and name the entry they supersede. BF-985's entries are unedited.
6. One broad gate and one PR (`Refs #1820`). The section 8 texts are posted after the merge.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**R-1.** The census sees only a `while <name|attribute>:` whose single await is a direct `gather`. Not detected (false negatives): a spin through `wait_for` or `asyncio.timeout` around a gather that is already done, and an expression condition. None exists today (AV1, AV4); the gap is considered and deferred. Flagged though safe (false positives): a loop that empties its container by rebinding it (`tasks = [...]`) or with `pop`/`popleft`, which condition 3 does not count as a prune. None exists on this tree: the orchestrator's AST census, with `pop`/`popleft` counted as prunes, still finds the same nine loops of conditions 1 and 2 without a prune call. Such a hit fails T3 loudly and is settled by extending condition 3.

**R-2.** What raised first in `test_continuous_historical_replay_matches_checked_bridge_wire` on run 44520999819 is unknown. After this fix, the next occurrence fails as an ordinary test with a traceback.

**R-3.** Whether stalls 36907487200, 41764125537 and 44395509240 had this cause is unknown (no stacks). A stall of another cause still writes dumps (BF-985).

### Premises to verify first-hand before building (each with its probe)

| P | Premise | Probe (assert it) |
|---|---|---|
| P1 | BF-987 is free | Re-run AV3, and confirm that `open-ads-report.md`'s BF row still says next free BF-987 after BF-986 merges |
| P2 | Red first: the census and T1 see exactly the defect | With only 7.1 added: T3 fails listing exactly `tests/test_ad1204_approval_resumes_the_turn.py:132, :725, :791`, `tests/test_ad1206_repair_issue.py:61`, `tests/test_ad1228_standing_interests.py:130`, `tests/test_ad1341_s4_stand_down.py:1275`, `tests/test_bf708_capability_notice.py:246` and `tests/test_bf722_approval_transaction_integrity.py:179`, and nothing else. Each of the six T1 cases fails with "stopped by clearing the set" (not "premise:"). T2 passes. Record the times (expect about 5 s per T1 case) and the six files' sha256 |
| P3 | Each SEARCH matches once | `rg -c` the first line of each SEARCH in its file; each of the 10 blocks (eight loop pairs in 7.2 to 7.7, the two tracker pairs in 7.8 and 7.9) resolves to exactly one location |
| P4 | Every `src/` or `tests/` `.py` that contains `gather(` decodes as UTF-8 and parses | T3 on the base tree raises no parse or decode error |
| P5 | The emit-path premise holds on both OSes | T1[ad1206-bus-through-emit] green on Windows 3.12.13 (build host) and in the PR's Linux CI (3.12.x). If its premise assertion fails on either, stop and report; do not loosen it |
| P6 | Bounded cost, no regression | M1 focused gate green; `--durations=0`: record each T1 case and T3. a0's bounds were estimates, not measurements (a green T1 case takes milliseconds; T3 parses about 192 files in a few seconds). Stop and report if a green T1 case exceeds 2 s or T3 exceeds 30 s, both far below the 180 s per-test timeout |
| P7 | B5 (#1801) does not edit the eight loops | On B5's oracle tree, run `git diff --stat <B5 base> <B5 head> -- ` followed by the six edited files: no change at S1 to S8. If it overlaps, B5 rebases its SEARCH after BF-987 |

**Only later CI can show:** that a stall of this cause no longer occurs (R-3 measures it over runs), and that a stall of another cause still writes its dumps (BF-985).
