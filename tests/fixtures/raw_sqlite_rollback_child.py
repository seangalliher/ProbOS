"""Child process of the BF-882 raw-sqlite3 test (tests/test_issue1419_failed_start_rollback.py).

A component whose stop() fails twice holds a raw ``sqlite3.Connection`` (``check_same_thread=False``)
on which a long statement is running on another thread, and the startup rollback runs. The rollback's
last resort used to call ``close()`` on that connection from the event-loop thread, and the interpreter
died with an access violation (exit code -1073741819 on Windows) when the statement resumed. It must
leave a raw connection alone: closing one is never safe from here, because whether a statement is
running on another thread is not something the rollback can know.

It prints a JSON report and ``MAIN_DONE``, arms a ``faulthandler`` watchdog and RETURNS, like
``failed_start_child.py``. The crash is therefore the parent's assertion (the exit code), and a
non-daemon thread left behind would keep the process alive until the watchdog dumps it and exits 1.
The scenario runs in a process of its own because a regression here is not a failed assertion but a
dead interpreter, which must not take the test worker with it.

``PROBOS_RAW_STATEMENT_SECONDS`` is how long the statement runs (default 2).

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
from pathlib import Path
from typing import Any

for _key, _value in (
    ("PROBOS_NATS_ENABLED", "false"),
    ("HF_HUB_OFFLINE", "1"),
    ("PROBOS_DISABLE_OVERLAY", "1"),
):
    os.environ.setdefault(_key, _value)

_EXPECTED_SRC = os.environ.get("PROBOS_LIFECYCLE_EXPECT_SRC", "")
_HANG_DUMP = os.environ.get("PROBOS_LIFECYCLE_HANGDUMP", "")
_STATEMENT_SECONDS = float(os.environ.get("PROBOS_RAW_STATEMENT_SECONDS", "2"))
_WATCHDOG_SECONDS = 30


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


async def _rollback_with_a_statement_running(base: Path) -> dict[str, Any]:
    warnings: list[str] = []

    class _CollectWarnings(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING and record.getMessage().startswith("BF-882"):
                warnings.append(record.getMessage()[:600])

    shutdown_logger = logging.getLogger("probos.startup.shutdown")
    collector = _CollectWarnings(level=logging.WARNING)
    shutdown_logger.addHandler(collector)

    raw = sqlite3.connect(str(base / "raw.db"), check_same_thread=False)
    running = threading.Event()
    outcome: list[Any] = []

    def slow(seconds: float) -> int:
        running.set()
        time.sleep(seconds)
        return 1

    raw.create_function("slow", 1, slow)

    def statement() -> None:
        try:
            outcome.append(raw.execute("select slow(?)", (_STATEMENT_SECONDS,)).fetchall())
        except Exception as error:  # noqa: BLE001 -- the parent reads the report, whatever happened
            outcome.append(f"{type(error).__name__}: {error}")

    worker = threading.Thread(target=statement, name="long-statement")
    worker.start()
    report: dict[str, Any] = {"statement_was_running": running.wait(30)}
    runtime = BareRuntime(
        base / "data",
        config=SystemConfig(memory=MemoryConfig(shutdown_write_grace_s=0.0, shutdown_dispatch_grace_s=0.0)),
        started=False,
    )
    component = _FailsToStop(_conn=raw)
    runtime.acm = component
    try:
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
        report["rollback_returned"] = True
        report["statement_still_running_at_return"] = worker.is_alive()
    finally:
        shutdown_logger.removeHandler(collector)
    worker.join(60)
    report["component_stops"] = component.stops
    report["statement_outcome"] = outcome[0] if outcome else None
    try:
        raw.execute("select 1").fetchall()
        report["connection_usable_after"] = True
    except sqlite3.ProgrammingError:
        report["connection_usable_after"] = False
    raw.close()
    report["raw_warnings"] = [w for w in warnings if w.startswith("BF-882: last-resort leaves")]
    return report


def main() -> int:
    report = asyncio.run(_rollback_with_a_statement_running(Path.cwd()))
    print("REPORT " + json.dumps(report), flush=True)
    print("MAIN_DONE", flush=True)
    dump = open(_HANG_DUMP, "w") if _HANG_DUMP else sys.stderr
    faulthandler.dump_traceback_later(_WATCHDOG_SECONDS, exit=True, file=dump)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.exit(code)
