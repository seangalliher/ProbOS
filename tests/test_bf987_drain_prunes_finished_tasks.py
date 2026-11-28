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
