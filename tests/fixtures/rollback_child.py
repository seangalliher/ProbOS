"""Child process of the BF-882 last-resort tests (tests/test_issue1419_failed_start_rollback.py).

Each scenario runs ``shutdown(runtime, rollback=True)`` against a runtime double under
``asyncio.run()``, in a process of its own, because what it proves is about the interpreter and
not about an assertion: a regression is a dead process (``raw_sqlite``) or one that never exits
(``abandoned_close``), and neither can be reported by the test worker that hosts it.

The child prints a JSON report and ``MAIN_DONE``, arms a ``faulthandler`` watchdog and RETURNS,
like ``failed_start_child.py``: a non-daemon thread or a task left behind that keeps the process
alive is dumped into ``PROBOS_LIFECYCLE_HANGDUMP`` and ends it with exit code 1, and a clean exit
is exit code 0 with an empty dump. ``main_done_at`` is when ``main`` finished and
``loop_closed_at`` is when ``asyncio.run`` returned (the loop shut down), so the parent can
measure how long each took.

``PROBOS_ROLLBACK_SCENARIO`` selects the scenario; ``PROBOS_ROLLBACK_STATEMENT_SECONDS`` is how
long its statement runs (default 2).

``raw_sqlite``: a component whose stop() fails holds a raw ``sqlite3.Connection``
(``check_same_thread=False``) on which a long statement is running on another thread. The
rollback's last resort used to call ``close()`` on it from the event-loop thread and the
interpreter died with an access violation (exit code -1073741819 on Windows) when the statement
resumed. It must leave a raw connection alone: whether a statement is running on another thread
is not something the rollback can know.

``abandoned_close``: a component whose stop() fails holds an aiosqlite connection whose worker
thread is held by a long statement. The rollback's last-resort close of it is queued behind that
statement, is not done within the bound and is ABANDONED (cancelled, not awaited). ``main`` then
returns with the abandoned close and the statement still pending, so ``asyncio.run`` shuts the
loop down: it cancels and awaits every pending task. A close awaits a plain future, so that
cancellation ends it at once and the loop closes while the statement is still running; the
non-daemon worker thread ends the process when the statement does. A task that ignored
cancellation here would keep the loop, and so the process, from ending: the reason a stop()
that already failed is never called again.

Exit code 3: probos was imported from somewhere other than ``PROBOS_LIFECYCLE_EXPECT_SRC``.

This module is import-safe: the checks and side effects run only when it is run as a script.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiosqlite

for _key, _value in (
    ("PROBOS_NATS_ENABLED", "false"),
    ("HF_HUB_OFFLINE", "1"),
    ("PROBOS_DISABLE_OVERLAY", "1"),
):
    os.environ.setdefault(_key, _value)

_EXPECTED_SRC = os.environ.get("PROBOS_LIFECYCLE_EXPECT_SRC", "")
_HANG_DUMP = os.environ.get("PROBOS_LIFECYCLE_HANGDUMP", "")
_SCENARIO = os.environ.get("PROBOS_ROLLBACK_SCENARIO", "")
_STATEMENT_SECONDS = float(os.environ.get("PROBOS_ROLLBACK_STATEMENT_SECONDS", "2"))
_RUN_WATCHDOG_SECONDS = 60  # one scenario, including the loop shutting down
_WATCHDOG_SECONDS = 30  # after main returns


def _probos_comes_from_the_expected_source() -> bool:
    import probos

    return bool(_EXPECTED_SRC) and Path(probos.__file__).resolve().is_relative_to(
        Path(_EXPECTED_SRC).resolve()
    )


if __name__ == "__main__" and not _probos_comes_from_the_expected_source():
    print(f"probos is not imported from PROBOS_LIFECYCLE_EXPECT_SRC={_EXPECTED_SRC!r}", flush=True)
    sys.exit(3)

from probos.config import MemoryConfig, SystemConfig  # noqa: E402
from probos.startup import shutdown as shutdown_module  # noqa: E402
from tests.fixtures.runtime_lifecycle import BareRuntime  # noqa: E402


class _FailsToStop:
    """A component whose stop() always raises, and which holds what it is given."""

    def __init__(self, **held: Any) -> None:
        self.stops = 0
        for name, value in held.items():
            setattr(self, name, value)

    async def stop(self) -> None:
        self.stops += 1
        raise RuntimeError(f"stop refused ({self.stops})")


def _runtime(base: Path) -> BareRuntime:
    return BareRuntime(
        base / "data",
        config=SystemConfig(memory=MemoryConfig(shutdown_write_grace_s=0.0, shutdown_dispatch_grace_s=0.0)),
        started=False,
    )


class _RollbackWarnings(logging.Handler):
    """The BF-882 warnings the rollback logs, by their start."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage().startswith("BF-882"):
            self.messages.append(record.getMessage()[:600])

    def __enter__(self) -> _RollbackWarnings:
        logging.getLogger("probos.startup.shutdown").addHandler(self)
        return self

    def __exit__(self, *exc_info: object) -> None:
        logging.getLogger("probos.startup.shutdown").removeHandler(self)


def _slow_function(started: threading.Event, started_at: list[float]) -> Callable[[float], int]:
    def slow(seconds: float) -> int:
        started_at.append(time.time())
        started.set()
        time.sleep(seconds)
        return 1

    return slow


async def _raw_sqlite(base: Path) -> dict[str, Any]:
    raw = sqlite3.connect(str(base / "raw.db"), check_same_thread=False)
    running = threading.Event()
    outcome: list[Any] = []
    raw.create_function("slow", 1, _slow_function(running, []))

    def statement() -> None:
        try:
            outcome.append(raw.execute("select slow(?)", (_STATEMENT_SECONDS,)).fetchall())
        except Exception as error:  # noqa: BLE001 -- the parent reads the report, whatever happened
            outcome.append(f"{type(error).__name__}: {error}")

    worker = threading.Thread(target=statement, name="long-statement")
    worker.start()
    report: dict[str, Any] = {"statement_was_running": running.wait(30)}
    runtime = _runtime(base)
    component = _FailsToStop(_conn=raw)
    runtime.acm = component
    with _RollbackWarnings() as warnings:
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
    report["rollback_returned"] = True
    report["statement_still_running_at_return"] = worker.is_alive()
    worker.join(60)
    report["component_stops"] = component.stops
    report["statement_outcome"] = outcome[0] if outcome else None
    try:
        raw.execute("select 1").fetchall()
        report["connection_usable_after"] = True
    except sqlite3.ProgrammingError:
        report["connection_usable_after"] = False
    raw.close()
    report["raw_warnings"] = [w for w in warnings.messages if w.startswith("BF-882: last-resort leaves")]
    return report


async def _abandoned_close(base: Path) -> dict[str, Any]:
    shutdown_module._LAST_RESORT_SECONDS = 0.3  # the bound; the statement outlasts it by far
    running = threading.Event()
    started_at: list[float] = []
    connection = await aiosqlite.connect(str(base / "long.db"))
    await connection.create_function("slow", 1, _slow_function(running, started_at))

    async def long_statement() -> Any:
        return await connection.execute("select slow(?)", (_STATEMENT_SECONDS,))

    statement = asyncio.create_task(long_statement())
    deadline = time.time() + 30
    while not running.is_set() and time.time() < deadline:  # not to_thread: asyncio.run awaits its executor
        await asyncio.sleep(0.01)
    report: dict[str, Any] = {
        "statement_was_running": running.is_set(),
        "statement_started_at": started_at[0] if started_at else None,
        "statement_seconds": _STATEMENT_SECONDS,
    }
    runtime = _runtime(base)
    component = _FailsToStop(_db=connection)
    runtime.acm = component
    with _RollbackWarnings() as warnings:
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
    report["rollback_returned_at"] = time.time()
    report["component_stops"] = component.stops
    report["abandoned_tasks_at_return"] = len(shutdown_module._abandoned_tasks)
    report["statement_done_at_return"] = statement.done()
    report["close_abandoned"] = any(" was abandoned: " in message for message in warnings.messages)
    return report  # the abandoned close and the statement are still pending: asyncio.run must end them


_SCENARIOS: dict[str, Callable[[Path], Awaitable[dict[str, Any]]]] = {
    "raw_sqlite": _raw_sqlite,
    "abandoned_close": _abandoned_close,
}


def main() -> int:
    dump = open(_HANG_DUMP, "w") if _HANG_DUMP else sys.stderr
    # asyncio.run cancels and awaits every pending task when it shuts the loop down, and one that
    # ignores cancellation keeps it from ever returning: cut that short with a dump of every stack
    # instead of waiting for the parent's timeout.
    faulthandler.dump_traceback_later(_RUN_WATCHDOG_SECONDS, exit=True, file=dump)
    report = asyncio.run(_SCENARIOS[_SCENARIO](Path.cwd()))
    faulthandler.cancel_dump_traceback_later()
    report["loop_closed_at"] = time.time()  # asyncio.run returned: every pending task was cancelled and awaited
    report["main_done_at"] = time.time()
    print("REPORT " + json.dumps(report), flush=True)
    print("MAIN_DONE", flush=True)
    faulthandler.dump_traceback_later(_WATCHDOG_SECONDS, exit=True, file=dump)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.exit(code)
