"""BF-891 (#1542): ProcedureStore's write lock is loop-owned, and an abandoned index write is rolled back.

Before the fix a ``threading.Lock`` was held across the awaits of every SQLite index write, so a
second writer blocked the event-loop thread and the first writer could never resume. A write
cancelled (or failed) after its first statement also left a half-written row pending on the
store's one connection, for the next writer's ``commit`` to make durable.

How these tests prove it:

- Overlap tests run each scenario on a private event loop in a daemon thread
  (``_run_on_private_loop``). A writer that blocks the loop thread cannot report its own hang, so
  the pytest thread is the watchdog: a hang FAILS the test (``hung``) instead of hanging the suite,
  and the harness frees any plain ``threading.Lock`` the store holds so the loop thread can finish
  its scenario and close the store instead of staying blocked with an open connection.
- Every overlap swaps in an ``_ObservedLock`` and requires ``contended >= 1``: the calls really met
  inside the critical section. The single-save and sequential controls require ``contended == 0``.
- Cancellation and failure tests run on the pytest loop against a gated connection
  (``_GatedFactory``) that parks one chosen statement, so a cancel lands at a known point.
- Committed state is read only through an independent read-only ``sqlite3`` connection
  (``_committed_row``), which cannot see a write the store's own connection has not committed.
- ``scan_sync_with_awaits`` is the structural guard: no synchronous ``with`` block inside an
  ``async def`` of procedure_store.py may contain an ``await``, whatever its lock is named.
"""

from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
import threading
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive import procedure_store as procedure_store_module
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.storage.sqlite_factory import default_factory

# Budgets in seconds. The worst single test is start (120) + scenario (15) + release loop (10) +
# join (10) = 155, under pytest-timeout's 180 (pyproject.toml). Every cancellation wait is 5.
_GATE_WAIT_S = 5.0
_RELEASE_TRIES = 100
_RELEASE_INTERVAL_S = 0.1
_JOIN_S = 10.0
_THREAD_LOCK_TYPE = type(threading.Lock())
_COUNTER_COLUMNS = (
    "total_selections",
    "total_applied",
    "total_completions",
    "total_fallbacks",
    "consecutive_successes",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _proc(
    pid: str,
    *,
    level: int = 1,
    parents: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> Procedure:
    """A minimal Procedure (same shape as tests/test_procedure_store.py::_make_procedure)."""
    return Procedure(
        id=pid,
        name=f"Procedure {pid}",
        description=f"BF-891 test procedure {pid}",
        steps=[
            ProcedureStep(step_number=1, action="Do thing"),
            ProcedureStep(step_number=2, action="Do other thing"),
        ],
        intent_types=["read"],
        origin_cluster_id=f"cluster-{pid}",
        origin_agent_ids=["agent-a"],
        provenance=["ep-1", "ep-2"],
        extraction_date=time.time(),
        evolution_type="CAPTURED",
        is_active=True,
        is_negative=False,
        generation=0,
        parent_procedure_ids=list(parents),
        compilation_level=level,
        tags=list(tags),
    )


class _ObservedLock(asyncio.Lock):
    """An asyncio.Lock that counts the acquires that found it already held.

    ``contended >= 1`` after a gather proves the calls really met inside the critical section;
    ``contended == 0`` in the controls proves the counter does not fire without an overlap.
    """

    def __init__(self) -> None:
        super().__init__()
        self.contended = 0

    async def acquire(self) -> bool:
        if self.locked():
            self.contended += 1
        return await super().acquire()


_Scenario = Callable[[ProcedureStore, _ObservedLock], Awaitable[None]]


@dataclass
class _LoopRun:
    """What one private-loop scenario did.

    ``stage``: ``start`` = the store never finished starting (a premise failure, not a hang);
    ``scenario`` = the scenario began and had not finished (or raised); ``done`` = it finished.
    """

    hung: bool = False
    error: BaseException | None = None
    stage: str = "start"
    thread: threading.Thread | None = None


def _release_thread_locks(store: ProcedureStore, finished: threading.Event) -> None:
    """After a hang, free every held plain ``threading.Lock`` in ``vars(store)`` so the loop can unwind.

    Any thread may release a ``threading.Lock``. Repeats because a mutant's one shared lock is
    taken again by the next writer the moment the loop thread runs.
    """
    for _ in range(_RELEASE_TRIES):
        for value in list(vars(store).values()):
            if isinstance(value, _THREAD_LOCK_TYPE) and value.locked():
                try:
                    value.release()
                except RuntimeError:
                    pass  # the loop thread released it between the check and here
        if finished.wait(_RELEASE_INTERVAL_S):
            return


def _run_on_private_loop(
    tmp_path: Path,
    scenario: _Scenario,
    *,
    start_budget_s: float = 120.0,
    budget_s: float = 15.0,
) -> _LoopRun:
    """Run ``scenario(store, observed_lock)`` on a private loop in a daemon thread, with a watchdog.

    The pytest thread waits on ``threading.Event``s: ``start_budget_s`` for the store to start, then
    ``budget_s`` for the scenario. A loop blocked by a thread lock cannot report its own hang, which
    is why the watchdog is another thread and why nothing here ``join()``s without a timeout.
    """
    run = _LoopRun()
    started = threading.Event()
    finished = threading.Event()
    abandoned = threading.Event()
    holder: dict[str, ProcedureStore] = {}

    async def main() -> None:
        store = ProcedureStore(data_dir=tmp_path / "procedures")
        holder["store"] = store
        try:
            await store.start()
            if abandoned.is_set():
                return
            lock = _ObservedLock()
            store._write_lock = lock
            run.stage = "scenario"
            started.set()
            await scenario(store, lock)
            run.stage = "done"
        finally:
            await store.stop()

    def target() -> None:
        try:
            asyncio.run(main())
        except BaseException as exc:  # reported by the pytest thread through run.error
            run.error = exc
        finally:
            started.set()
            finished.set()

    thread = threading.Thread(target=target, name="bf891-private-loop", daemon=True)
    run.thread = thread
    thread.start()
    if not started.wait(start_budget_s):
        abandoned.set()  # the loop thread must not run the scenario if it ever finishes starting
        return run
    if not finished.wait(budget_s):
        run.hung = True
        _release_thread_locks(holder["store"], finished)
    thread.join(_JOIN_S)
    return run


@dataclass
class _Gate:
    """One armed one-shot gate: on a match ``entered`` is set and the statement waits on ``release``."""

    predicate: Callable[[str], bool]
    entered: asyncio.Event
    release: asyncio.Event


class _GatedConnection:
    """Wraps the real procedures.db connection; ``execute`` parks on the next armed gate whose predicate matches."""

    def __init__(self, real: Any, gates: list[_Gate]) -> None:
        self._real = real
        self._gates = gates

    async def execute(self, sql: str, *params: Any, **kwargs: Any) -> Any:
        if self._gates and self._gates[0].predicate(sql):
            gate = self._gates.pop(0)
            gate.entered.set()
            await gate.release.wait()
        return await self._real.execute(sql, *params, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _GatedFactory:
    """A ConnectionFactory that gates only procedures.db, so the AD-1326 ledger's connection is untouched."""

    def __init__(self) -> None:
        self._gates: list[_Gate] = []
        self.connection: _GatedConnection | None = None

    async def connect(self, db_path: str) -> Any:
        real = await default_factory.connect(db_path)
        if Path(db_path).name != "procedures.db":
            return real
        self.connection = _GatedConnection(real, self._gates)
        return self.connection

    def arm(self, predicate: Callable[[str], bool]) -> _Gate:
        """Arm a one-shot gate; gates are consumed in the order they were armed."""
        gate = _Gate(predicate=predicate, entered=asyncio.Event(), release=asyncio.Event())
        self._gates.append(gate)
        return gate


def _is_snapshot_select(sql: str) -> bool:
    return sql.startswith("SELECT content_snapshot FROM procedure_records WHERE id")


def _is_rollback(sql: str) -> bool:
    return sql.strip().upper() == "ROLLBACK"


@dataclass
class _Rig:
    store: ProcedureStore
    factory: _GatedFactory
    connection: _GatedConnection
    db_path: Path


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[_Rig]:
    """A started ProcedureStore on the pytest loop whose procedures.db connection can be gated."""
    factory = _GatedFactory()
    store = ProcedureStore(data_dir=tmp_path / "procedures", connection_factory=factory)
    await store.start()
    try:
        assert factory.connection is not None, "premise: the store opened procedures.db through the gated factory"
        yield _Rig(store=store, factory=factory, connection=factory.connection, db_path=_db_file(tmp_path))
    finally:
        await store.stop()


def _db_file(tmp_path: Path) -> Path:
    return tmp_path / "procedures" / "procedures.db"


def _committed_row(db_path: Path, pid: str, *columns: str) -> dict[str, Any] | None:
    """One procedure_records row as the database file holds it, read through a connection of its own.

    Read-only and independent of the store's connection, so a write the store has not committed
    (a half-written row pending on its connection) is invisible here. With no ``columns`` it reads
    ``is_active, superseded_by, content_snapshot``.
    """
    wanted = columns or ("is_active", "superseded_by", "content_snapshot")
    assert all(name.isidentifier() for name in wanted), wanted
    uri = f"{db_path.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as conn:
        row = conn.execute(
            f"SELECT {', '.join(wanted)} FROM procedure_records WHERE id = ?", (pid,)
        ).fetchone()
    return None if row is None else dict(zip(wanted, row))


def _suspends(body: Sequence[ast.AST]) -> bool:
    """Whether running ``body`` can suspend the coroutine: an await, an async with or an async for.

    Nested defs and lambdas are not descended into: defining a coroutine inside a block does not run it there.
    """
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Await, ast.AsyncWith, ast.AsyncFor)):
            return True
        if isinstance(node, ast.comprehension) and node.is_async:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return False


def scan_sync_with_awaits(source: str) -> list[int]:
    """Line numbers of the synchronous ``with`` blocks, inside an ``async def``, whose body can suspend (G1)."""
    hits: list[int] = []

    def walk(node: ast.AST, in_async: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                walk(child, True)
            elif isinstance(child, (ast.FunctionDef, ast.Lambda)):
                walk(child, False)
            else:
                if in_async and isinstance(child, ast.With) and _suspends(child.body):
                    hits.append(child.lineno)
                walk(child, in_async)

    walk(ast.parse(source), False)
    return sorted(hits)


def _describe(error: BaseException | None) -> str:
    if error is None:
        return "no exception"
    return "".join(traceback.format_exception(error)).strip()


def _assert_ran(run: _LoopRun) -> None:
    """The harness verdict: the store started (premise), the loop did not hang, the scenario did not raise."""
    assert run.stage != "start", (
        f"premise: the store did not finish starting, so this is not a hang ({_describe(run.error)})"
    )
    assert not run.hung, (
        f"the event loop stopped making progress in stage {run.stage!r}: "
        "a writer blocked the loop thread, which is the #1542 failure"
    )
    assert run.error is None, f"the scenario raised: {_describe(run.error)}"


async def _gather(*aws: Awaitable[Any]) -> list[Any]:
    """Run the awaitables concurrently; exceptions come back as values so none is left running."""
    return list(await asyncio.gather(*aws, return_exceptions=True))


async def _seed(store: ProcedureStore, *procedures: Procedure) -> None:
    for procedure in procedures:
        await store.save(procedure)


def _failures(results: Sequence[Any]) -> list[BaseException]:
    return [item for item in results if isinstance(item, BaseException)]


def _outcome(task: asyncio.Task[Any]) -> str:
    if not task.done():
        return "still running"
    if task.cancelled():
        return "cancelled"
    error = task.exception()
    return f"raised {error!r}" if error is not None else f"returned {task.result()!r}"


async def _settle(task: asyncio.Task[Any]) -> None:
    """Wait (bounded) for the task to finish, whatever way it ends."""
    done, _pending = await asyncio.wait({task}, timeout=_GATE_WAIT_S)
    assert done, f"the task did not finish within {_GATE_WAIT_S} s: {_outcome(task)}"


async def _drain(task: asyncio.Task[Any], *gates: _Gate) -> None:
    """Failure-path hygiene: open every gate and cancel the task so no parked coroutine outlives its test."""
    for gate in gates:
        gate.release.set()
    if not task.done():
        task.cancel()
    await asyncio.wait({task}, timeout=_GATE_WAIT_S)
    if task.done() and not task.cancelled():
        task.exception()  # mark retrieved: the test already reported the outcome


# ---------------------------------------------------------------------------
# The harness's own negative control
# ---------------------------------------------------------------------------


def test_harness_reports_a_blocked_loop_instead_of_hanging(tmp_path: Path) -> None:
    """Negative control: a plain threading.Lock held across an await blocks the loop thread (the #1542 shape).

    If the watchdog could not fail on this, every ``not hung`` below would prove nothing.
    """

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        probe = threading.Lock()
        setattr(store, "_bf891_probe_lock", probe)  # in vars(store): the watchdog frees it after the budget

        async def hold() -> None:
            with probe:
                await asyncio.sleep(0.05)

        await asyncio.gather(hold(), hold(), return_exceptions=True)

    run = _run_on_private_loop(tmp_path, scenario, budget_s=2)

    assert run.stage != "start", f"premise: the store did not finish starting ({_describe(run.error)})"
    assert run.hung, "the harness did not report a loop blocked by a threading.Lock held across an await"
    assert run.thread is not None, "premise: the harness started a loop thread"
    assert not run.thread.is_alive(), "the loop thread was still running after the harness freed the lock"


# ---------------------------------------------------------------------------
# Controls: no overlap, no contention
# ---------------------------------------------------------------------------


def test_control_single_save_completes(tmp_path: Path) -> None:
    """Control: one save never contends, so ``contended >= 1`` in the overlap tests can only mean a real overlap."""
    db = _db_file(tmp_path)
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        seen["before"] = _committed_row(db, "p0")
        seen["saved"] = await store.save(_proc("p0"))
        seen["loaded"] = await store.get("p0")

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    assert seen["before"] is None, "premise: p0 does not exist before the save"
    assert seen["saved"] == "p0"
    assert seen["loaded"] is not None, "the saved procedure could not be read back"
    assert _committed_row(db, "p0") is not None, "the save did not commit"
    assert seen["lock"].contended == 0, "a single save reported contention on the write lock"


def test_control_sequential_saves_complete(tmp_path: Path) -> None:
    """Control: back-to-back saves never overlap, so they never contend."""
    db = _db_file(tmp_path)
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        seen["before"] = (_committed_row(db, "p1"), _committed_row(db, "p2"))
        seen["saved"] = [await store.save(_proc("p1")), await store.save(_proc("p2"))]

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    assert seen["before"] == (None, None), "premise: neither procedure exists before the saves"
    assert seen["saved"] == ["p1", "p2"]
    assert _committed_row(db, "p1") is not None and _committed_row(db, "p2") is not None, "a save did not commit"
    assert seen["lock"].contended == 0, "sequential saves reported contention on the write lock"


# ---------------------------------------------------------------------------
# Overlaps: every site group, on a real loop with a watchdog
# ---------------------------------------------------------------------------


def test_overlapping_saves_complete(tmp_path: Path) -> None:
    """Two saves meet inside the critical section (site 1); both must commit and the loop must not block."""
    db = _db_file(tmp_path)
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        seen["before"] = (_committed_row(db, "p3"), _committed_row(db, "p4"))
        seen["results"] = await _gather(store.save(_proc("p3")), store.save(_proc("p4")))

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    assert seen["before"] == (None, None), "premise: neither procedure exists before the saves"
    assert seen["results"] == ["p3", "p4"], seen["results"]
    for pid in ("p3", "p4"):
        row = _committed_row(db, pid)
        assert row is not None and row["is_active"] == 1, f"{pid} is not committed and active"
    assert seen["lock"].contended >= 1, "the two saves never met inside the critical section: no overlap happened"


def test_save_overlapping_deactivate_completes(tmp_path: Path) -> None:
    """The challenger-promotion overlap: a save and the supersede of its parent (sites 1 and 9)."""
    db = _db_file(tmp_path)
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        await store.save(_proc("p1"))
        seen["before"] = _committed_row(db, "p1")
        seen["results"] = await _gather(
            store.save(_proc("p5", parents=["p1"])),
            store.deactivate("p1", superseded_by="p5"),
        )

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    before = seen["before"]
    assert before is not None and before["is_active"] == 1 and before["superseded_by"] == "", (
        "premise: p1 is committed, active and not superseded before the overlap"
    )
    assert seen["results"] == ["p5", None], seen["results"]
    p5 = _committed_row(db, "p5")
    assert p5 is not None and p5["is_active"] == 1, "the challenger p5 is not committed and active"
    p1 = _committed_row(db, "p1")
    assert p1 is not None
    assert (p1["is_active"], p1["superseded_by"]) == (0, "p5"), "p1's columns were not superseded by p5"
    snapshot = json.loads(p1["content_snapshot"])
    assert snapshot["is_active"] is False and snapshot["superseded_by"] == "p5", "p1's snapshot was not superseded"
    assert seen["lock"].contended >= 1, "the save and the deactivate never met inside the critical section"


def test_overlapping_counter_writes_complete(tmp_path: Path) -> None:
    """The four counters and the consecutive-success bump overlap (sites 3, 4, 8)."""
    db = _db_file(tmp_path)
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        await store.save(_proc("p1"))
        seen["before"] = _committed_row(db, "p1", *_COUNTER_COLUMNS)
        seen["results"] = await _gather(
            store.record_selection("p1"),
            store.record_applied("p1"),
            store.record_completion("p1"),
            store.record_fallback("p1"),
            store.record_consecutive_success("p1"),
        )

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    assert seen["before"] == dict.fromkeys(_COUNTER_COLUMNS, 0), "premise: every counter of p1 starts at 0"
    assert seen["results"] == [None, None, None, None, 1], seen["results"]
    assert _committed_row(db, "p1", *_COUNTER_COLUMNS) == dict.fromkeys(_COUNTER_COLUMNS, 1), (
        "a counter increment was lost or doubled"
    )
    assert seen["lock"].contended >= 1, "the counter writes never met inside the critical section"


def test_overlapping_compilation_level_writes_complete(tmp_path: Path) -> None:
    """A promote, a demote and a consecutive-success reset overlap (sites 5, 6, 7)."""
    db = _db_file(tmp_path)
    columns = ("compilation_level", "consecutive_successes")
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        await _seed(store, _proc("p1", level=1), _proc("p2", level=3), _proc("p3", level=2))
        await store.record_consecutive_success("p3")
        seen["before"] = {pid: _committed_row(db, pid, *columns) for pid in ("p1", "p2", "p3")}
        seen["results"] = await _gather(
            store.promote_compilation_level("p1", 3),
            store.demote_compilation_level("p2", 1),
            store.reset_consecutive_successes("p3"),
        )

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    assert seen["before"] == {
        "p1": {"compilation_level": 1, "consecutive_successes": 0},
        "p2": {"compilation_level": 3, "consecutive_successes": 0},
        "p3": {"compilation_level": 2, "consecutive_successes": 1},
    }, "premise: the seeds must differ from the targets, or the writes below prove nothing"
    assert seen["results"] == [None, None, None], seen["results"]
    assert _committed_row(db, "p1", *columns) == {"compilation_level": 3, "consecutive_successes": 0}
    assert _committed_row(db, "p2", *columns) == {"compilation_level": 1, "consecutive_successes": 0}
    assert _committed_row(db, "p3", *columns) == {"compilation_level": 2, "consecutive_successes": 0}
    assert seen["lock"].contended >= 1, "the level writes never met inside the critical section"


def test_overlapping_promotion_status_writes_complete(tmp_path: Path) -> None:
    """A promotion request, an approval and a rejection overlap (sites 10, 11, 12)."""
    db = _db_file(tmp_path)
    columns = ("compilation_level", "total_selections", "total_completions", "promotion_status")
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        await _seed(store, _proc("p1"), _proc("p2"), _proc("p3", level=4))
        for _ in range(10):
            await store.record_selection("p3")
        for _ in range(10):
            await store.record_completion("p3")
        seen["before"] = {pid: _committed_row(db, pid, *columns) for pid in ("p1", "p2", "p3")}
        seen["results"] = await _gather(
            store.request_promotion("p3"),
            store.approve_promotion("p1", "captain", "d1"),
            store.reject_promotion("p2", "captain", "r"),
        )

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    before = seen["before"]
    assert (before["p3"]["compilation_level"], before["p3"]["total_selections"], before["p3"]["total_completions"]) == (
        4,
        10,
        10,
    ), "premise: p3 is seeded at level 4 with 10 selections and 10 completions, so it is eligible"
    assert all(before[pid]["promotion_status"] in (None, "private") for pid in ("p1", "p2", "p3")), (
        "premise: nothing is promoted, pending or rejected before the overlap"
    )
    request, approve, reject = seen["results"]
    assert isinstance(request, dict) and request["eligible"] is True, f"the promotion request was refused: {request!r}"
    assert approve is None and reject is None, seen["results"]
    assert _committed_row(db, "p3", "promotion_status") == {"promotion_status": "pending"}
    assert _committed_row(db, "p1", "promotion_status") == {"promotion_status": "approved"}
    assert _committed_row(db, "p2", "promotion_status") == {"promotion_status": "rejected"}
    assert seen["lock"].contended >= 1, "the promotion writes never met inside the critical section"


def test_overlapping_decay_and_archive_complete(tmp_path: Path) -> None:
    """The lifecycle sweeps overlap: one archives a stale Level 1, the other decays a stale Level 3 (sites 13, 14)."""
    db = _db_file(tmp_path)
    columns = ("is_active", "is_archived", "compilation_level", "total_selections")
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        await _seed(store, _proc("pA", level=1), _proc("pB", level=3))
        for _ in range(3):
            await store.record_selection("pB")
        seen["before"] = {pid: _committed_row(db, pid, *columns) for pid in ("pA", "pB")}
        future = time.time() + 91 * 86400
        seen["results"] = await _gather(
            store.archive_stale_procedures(now=future),
            store.decay_stale_procedures(now=future),
        )

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    before = seen["before"]
    assert (before["pA"]["is_active"], before["pA"]["is_archived"], before["pA"]["compilation_level"]) == (1, 0, 1), (
        "premise: pA is an active, unarchived Level 1"
    )
    assert (before["pB"]["compilation_level"], before["pB"]["total_selections"]) == (3, 3), (
        "premise: pB is a Level 3 with the 3 selections that make it decay-eligible"
    )
    archived, decayed = seen["results"]
    assert not _failures(seen["results"]), seen["results"]
    assert [entry["id"] for entry in archived] == ["pA"], archived
    assert [(e["id"], e["old_level"], e["new_level"]) for e in decayed] == [("pB", 3, 2)], decayed
    pa = _committed_row(db, "pA", *columns)
    assert pa is not None and (pa["is_active"], pa["is_archived"]) == (0, 1), "pA was not archived"
    pb = _committed_row(db, "pB", *columns)
    assert pb is not None and pb["compilation_level"] == 2, "pB was not decayed to Level 2"
    assert seen["lock"].contended >= 1, "the archive and the decay never met inside the critical section"


def test_overlapping_restore_delete_merge_complete(tmp_path: Path) -> None:
    """A restore, a delete and a merge overlap (sites 2, 15, 16, 17 and, through the merge's deactivate, 9)."""
    db = _db_file(tmp_path)
    columns = ("is_active", "is_archived", "compilation_level", "superseded_by")
    seen: dict[str, Any] = {}

    async def scenario(store: ProcedureStore, lock: _ObservedLock) -> None:
        seen["lock"] = lock
        await store.save(_proc("pArch"))
        seen["archived"] = await store.archive_stale_procedures(now=time.time() + 91 * 86400)
        await _seed(store, _proc("pDel"), _proc("pPrim"), _proc("pDup"))
        seen["before"] = {pid: _committed_row(db, pid, *columns) for pid in ("pArch", "pDel", "pPrim", "pDup")}
        seen["results"] = await _gather(
            store.restore_procedure("pArch"),
            store.delete("pDel"),
            store.merge_procedures("pPrim", "pDup"),
        )

    run = _run_on_private_loop(tmp_path, scenario)

    _assert_ran(run)
    before = seen["before"]
    assert [entry["id"] for entry in seen["archived"]] == ["pArch"], (
        f"premise: the sequential archive must take exactly pArch, got {seen['archived']!r}"
    )
    assert (before["pArch"]["is_active"], before["pArch"]["is_archived"]) == (0, 1), "premise: pArch is archived"
    assert before["pDel"] is not None, "premise: pDel exists before the delete"
    assert (before["pDup"]["is_active"], before["pDup"]["superseded_by"]) == (1, ""), (
        "premise: pDup is active and unmerged before the merge"
    )
    assert seen["results"] == [True, True, True], seen["results"]
    arch = _committed_row(db, "pArch", *columns)
    assert arch is not None and (arch["is_active"], arch["is_archived"], arch["compilation_level"]) == (1, 0, 1), (
        "pArch was not restored to active Level 1"
    )
    assert _committed_row(db, "pDel") is None, "pDel survived the delete"
    dup = _committed_row(db, "pDup", *columns)
    assert dup is not None and (dup["is_active"], dup["superseded_by"]) == (0, "pPrim"), (
        "pDup was not merged into pPrim"
    )
    assert seen["lock"].contended >= 1, "the restore, delete and merge never met inside the critical section"


# ---------------------------------------------------------------------------
# Cancellation and failure: the write lock, and the rollback of an abandoned write
# ---------------------------------------------------------------------------


async def test_cancel_while_waiting_writes_nothing_and_releases(rig: _Rig) -> None:
    """A save cancelled while it waits for the lock writes nothing and leaves the lock free."""
    store = rig.store
    lock = _ObservedLock()
    store._write_lock = lock
    task: asyncio.Task[Any] | None = None
    try:
        async with lock:
            task = asyncio.create_task(store.save(_proc("p9")))
            for _ in range(5):
                await asyncio.sleep(0)
            # Premises: the save reached the store's lock, found it held, and is parked there.
            assert lock.contended == 1, "premise: the save did not wait on the store's write lock"
            assert not task.done(), "premise: the save finished while the lock was held"
            task.cancel()
        await _settle(task)
        assert task.cancelled(), f"the waiting save ended as {_outcome(task)}, not as the caller's cancellation"
        assert not lock.locked(), "the cancelled waiter left the write lock held"
        assert await store.get("p9") is None
        assert _committed_row(rig.db_path, "p9") is None
        await store.save(_proc("p10"))
        assert _committed_row(rig.db_path, "p10") is not None, "the save after the cancellation did not commit"
        assert _committed_row(rig.db_path, "p9") is None, "the cancelled save's row became durable with the next commit"
    finally:
        if task is not None:
            await _drain(task)


async def test_cancel_while_holding_rolls_back_the_partial_deactivate(rig: _Rig) -> None:
    """A deactivate cancelled after its first UPDATE is rolled back: the next writer's commit must not publish it."""
    store = rig.store
    await store.save(_proc("p1"))
    before = _committed_row(rig.db_path, "p1")
    assert before is not None and before["is_active"] == 1, "premise: p1 is committed and active"
    gate = rig.factory.arm(_is_snapshot_select)
    task = asyncio.create_task(store.deactivate("p1", "x"))
    try:
        await asyncio.wait_for(gate.entered.wait(), _GATE_WAIT_S)
        # Premises: the write is half done inside the held lock, visible only to the store's own connection.
        assert store._write_lock.locked(), "premise: the deactivate is not holding the write lock"
        cursor = await rig.connection.execute(
            "SELECT is_active, superseded_by FROM procedure_records WHERE id = ?", ("p1",)
        )
        pending = await cursor.fetchone()
        assert tuple(pending) == (0, "x"), f"premise: the partial UPDATE is not pending on the connection: {pending!r}"
        independent = _committed_row(rig.db_path, "p1")
        assert independent is not None and independent["is_active"] == 1, (
            "premise: the independent read must not see the pending write"
        )
        task.cancel()
        await _settle(task)
        assert task.cancelled(), f"the deactivate ended as {_outcome(task)}, not as the caller's cancellation"
        assert not store._write_lock.locked(), "the cancelled deactivate left the write lock held"
        await store.save(_proc("p2"))
        assert _committed_row(rig.db_path, "p2") is not None, "the save after the cancellation did not commit"
        after = _committed_row(rig.db_path, "p1")
        assert after is not None
        assert (after["is_active"], after["superseded_by"]) == (1, ""), (
            "the cancelled deactivate's half-written row was committed by the next writer"
        )
        assert json.loads(after["content_snapshot"])["is_active"] is True
    finally:
        await _drain(task, gate)


async def test_second_cancel_during_rollback_holds_the_lock_until_it_ran(rig: _Rig) -> None:
    """A second cancel while the ROLLBACK is in flight must not free the lock before the ROLLBACK has run."""
    store = rig.store
    await store.save(_proc("p1"))
    before = _committed_row(rig.db_path, "p1")
    assert before is not None and before["is_active"] == 1, "premise: p1 is committed and active"
    select_gate = rig.factory.arm(_is_snapshot_select)
    rollback_gate = rig.factory.arm(_is_rollback)
    task = asyncio.create_task(store.deactivate("p1", "x"))
    try:
        await asyncio.wait_for(select_gate.entered.wait(), _GATE_WAIT_S)
        task.cancel()  # first cancel: the write is abandoned after its first statement
        await asyncio.wait_for(rollback_gate.entered.wait(), _GATE_WAIT_S)
        task.cancel()  # second cancel: lands while the ROLLBACK is in flight
        for _ in range(5):
            await asyncio.sleep(0)
        assert store._write_lock.locked(), "the second cancel freed the write lock before the ROLLBACK had run"
        assert not task.done(), f"the second cancel ended the write before its ROLLBACK ran: {_outcome(task)}"
        rollback_gate.release.set()
        await _settle(task)
        assert task.cancelled(), f"the deactivate ended as {_outcome(task)}, not as the caller's cancellation"
        assert not store._write_lock.locked(), "the write lock stayed held after the ROLLBACK ran"
        await store.save(_proc("p2"))
        assert _committed_row(rig.db_path, "p2") is not None, "the save after the cancellations did not commit"
        after = _committed_row(rig.db_path, "p1")
        assert after is not None
        assert (after["is_active"], after["superseded_by"]) == (1, ""), (
            "the half-written deactivate was committed by the next writer"
        )
    finally:
        await _drain(task, select_gate, rollback_gate)


async def test_failed_statement_rolls_back_the_partial_save(rig: _Rig) -> None:
    """A save whose second statement fails must not leave its first statement for the next commit to publish."""
    store = rig.store
    # Premise: FOREIGN KEY enforcement makes the lineage INSERT fail after the row INSERT ran.
    with pytest.raises(sqlite3.IntegrityError):
        await store.save(_proc("child", parents=["missing"]))
    assert not store._write_lock.locked(), "the failed save left the write lock held"
    await store.save(_proc("p2"))
    assert _committed_row(rig.db_path, "p2") is not None, "the save after the failure did not commit"
    assert _committed_row(rig.db_path, "child") is None, (
        "the failed save's row became durable, without its lineage, with the next commit"
    )


async def test_cancel_during_rollback_of_an_error_is_not_swallowed(rig: _Rig) -> None:
    """A cancel that arrives while an error is being rolled back reaches the caller as CancelledError."""
    store = rig.store
    gate = rig.factory.arm(_is_rollback)
    task = asyncio.create_task(store.save(_proc("child", parents=["missing"])))
    try:
        await asyncio.wait_for(gate.entered.wait(), _GATE_WAIT_S)
        # Premises: the foreign-key failure is being rolled back inside the held lock.
        assert store._write_lock.locked(), "premise: the failed save is not holding the write lock"
        assert not task.done(), f"premise: the save ended before its ROLLBACK ran: {_outcome(task)}"
        task.cancel()
        await asyncio.sleep(0)
        gate.release.set()
        await _settle(task)
        assert task.cancelled(), (
            f"the cancel was swallowed: the save ended as {_outcome(task)}, not as the caller's cancellation"
        )
        assert not store._write_lock.locked(), "the write lock stayed held after the ROLLBACK ran"
    finally:
        await _drain(task, gate)


# ---------------------------------------------------------------------------
# Structure: no thread lock across an await, and the lock's type
# ---------------------------------------------------------------------------


def test_no_sync_with_block_in_procedure_store_awaits() -> None:
    """G1: a synchronous ``with`` holding a lock across an await is the #1542 bug under any name."""
    source = Path(procedure_store_module.__file__).read_text(encoding="utf-8")
    sites = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.AsyncWith)]
    assert sites, "premise: procedure_store.py has no async with at all, so the scan would prove nothing"
    hits = scan_sync_with_awaits(source)
    assert hits == [], "a synchronous `with` block awaits while it is held: " + ", ".join(
        f"procedure_store.py:{line}" for line in hits
    )


def test_scanner_flags_a_sync_with_that_awaits() -> None:
    """Negative control: the scanner can fail, and it does not flag what is not the bug."""
    flagged = "async def f():\n    with self._x:\n        await g()\n"
    assert scan_sync_with_awaits(flagged) == [2]
    # An async with is the loop-owned form, not the bug.
    assert scan_sync_with_awaits("async def f():\n    async with self._x:\n        await g()\n") == []
    # A sync with that never suspends is fine.
    assert scan_sync_with_awaits("async def f():\n    with self._x:\n        y = 1\n") == []
    # Defining a coroutine inside the block does not run it there.
    nested = "async def f():\n    with self._x:\n        async def inner():\n            await g()\n"
    assert scan_sync_with_awaits(nested) == []
    # Every other way of suspending inside the block is flagged.
    assert scan_sync_with_awaits("async def f():\n    with self._x:\n        async with self._y: pass\n") == [2]
    assert scan_sync_with_awaits("async def f():\n    with self._x:\n        async for _ in g(): pass\n") == [2]
    assert scan_sync_with_awaits("async def f():\n    with self._x:\n        y = [i async for i in g()]\n") == [2]
    # The reported line is the sync with's own, even inside an async with.
    inside = "async def f():\n    async with self._lock:\n        with self._x:\n            await g()\n"
    assert scan_sync_with_awaits(inside) == [3]


def test_write_lock_is_loop_owned(tmp_path: Path) -> None:
    """A store built with no running loop owns an asyncio.Lock, which binds to a loop on first contention."""
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()  # premise: this test really runs with no loop
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    assert isinstance(store._write_lock, asyncio.Lock), (
        f"the write lock is a {type(store._write_lock).__name__}, which a second writer can block the loop on"
    )
    assert not store._write_lock.locked()
