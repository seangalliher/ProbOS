"""Child process of the BF-882 subprocess test (tests/test_issue1419_failed_start_rollback.py).

Fails two starts -- one right after the Phase-1 infrastructure opened its aiosqlite
workers, one at the ``started`` event-log row, when ``_started`` is already True and
the YeomanAgent singleton is held -- each in its own ``asyncio.Runner`` (what
pytest-asyncio gives every test), then boots a third runtime and stops it, all in this
one process. It prints a JSON report, then ``MAIN_DONE``, arms a ``faulthandler``
watchdog and RETURNS.

What the parent asserts is therefore about the interpreter, not just the runtime: a
non-daemon thread left behind keeps the process alive after ``main`` returns, the
watchdog dumps every stack into ``PROBOS_LIFECYCLE_HANGDUMP`` and ``_exit``s with 1, and
a clean exit is exit code 0 with an empty dump. Before BF-882, 13 of 15 failed-start
children hung this way.

``PROBOS_LIFECYCLE_BREAK_STEPS`` (comma-separated runtime attributes, each optionally
``attribute=before`` or ``attribute=unkillable``) makes each named component's ``stop()``
raise at the moment the injected failure fires, so the rollback has to go on past a teardown
step that fails. The default raises AFTER the component's real ``stop()`` ran (it has cleaned
up); ``=before`` raises at once, so the component keeps its connections open and only the
rollback's last-resort close can release them; ``=unkillable`` raises at once too, and any
LATER call ignores every cancellation forever, so a rollback that asked the component to stop
again would leave a task that ``asyncio.Runner`` cancels and awaits when it shuts the loop
down, and this process would never exit: the watchdog around each loop shutdown (30 s) dumps
every stack and ends it with exit code 1. The attributes must exist at the phase under test;
the report lists how often each broken ``stop()`` was called, how often it really ran, how
many cancellations it ignored, and the BF-882 warnings the rollback logged. ``main_done_at``
is when ``main`` finished, so the parent can measure how long the process took to exit.

Exit code 3: probos was imported from somewhere other than ``PROBOS_LIFECYCLE_EXPECT_SRC``.

This module is import-safe: the checks and side effects run only when it is run as a
script. A repository-wide ``git grep`` for consumer tests lists it (it names
``YeomanAgent``), and pytest imports every file it is given.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import os
import sys
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


def _parse_break_steps(raw: str) -> list[tuple[str, str]]:
    """``"acm,ward_room=before"`` -> ``[("acm", "after"), ("ward_room", "before")]``."""
    steps: list[tuple[str, str]] = []
    for item in raw.split(","):
        attribute, _, when = item.strip().partition("=")
        if attribute.strip():
            steps.append((attribute.strip(), when.strip() or "after"))
    return steps


_BREAK_STEPS = _parse_break_steps(os.environ.get("PROBOS_LIFECYCLE_BREAK_STEPS", ""))
_WATCHDOG_SECONDS = 30  # after main returns
_SHUTDOWN_WATCHDOG_SECONDS = 30  # one loop shutting down, which is milliseconds when nothing resists
_dump_file: Any = None  # the faulthandler timers need their file kept open


def _probos_comes_from_the_expected_source() -> bool:
    import probos

    return bool(_EXPECTED_SRC) and Path(probos.__file__).resolve().is_relative_to(
        Path(_EXPECTED_SRC).resolve()
    )


if __name__ == "__main__" and not _probos_comes_from_the_expected_source():
    print(f"probos is not imported from PROBOS_LIFECYCLE_EXPECT_SRC={_EXPECTED_SRC!r}", flush=True)
    sys.exit(3)

import pytest  # noqa: E402

from probos.cognitive.yeoman import YeomanAgent  # noqa: E402
from tests.fixtures.abortive_self_pipe import install_abortive_self_pipe  # noqa: E402
from tests.fixtures.codebase_index_memo import install_codebase_index_memo  # noqa: E402
from tests.fixtures.runtime_factory import make_runtime  # noqa: E402
from tests.fixtures.runtime_lifecycle import (  # noqa: E402
    BrokenStop,
    InjectedStartFailure,
    break_stop,
    inject_start_failure,
    lifecycle_config,
)


async def _failed_start(base: Path, phase: str) -> dict[str, Any]:
    runtime = make_runtime(base, config=lifecycle_config(base, zero_grace=True))
    patches = pytest.MonkeyPatch()
    report: dict[str, Any] = {"phase": phase}
    broken_stops: list[BrokenStop] = []
    rollback_warnings: list[str] = []

    class _CollectWarnings(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING and record.getMessage().startswith("BF-882"):
                rollback_warnings.append(record.getMessage()[:400])

    shutdown_logger = logging.getLogger("probos.startup.shutdown")
    collector = _CollectWarnings(level=logging.WARNING)
    shutdown_logger.addHandler(collector)

    def break_the_requested_steps(failing_runtime: Any) -> None:
        broken_stops.extend(
            break_stop(failing_runtime, attribute, when=when) for attribute, when in _BREAK_STEPS
        )

    try:
        failure = inject_start_failure(
            patches, runtime, phase, on_fire=break_the_requested_steps if _BREAK_STEPS else None,
        )
        try:
            await runtime.start()
            report["start_raised"] = None
        except InjectedStartFailure as error:
            report["start_raised"] = str(error)
        report["facts"] = failure.facts
        report["started_after"] = runtime._started
        report["pools_after"] = len(runtime.pools)
        report["registry_after"] = runtime.registry.count
        report["yeoman_after"] = YeomanAgent._live_instance_count
        report["broken_stop_calls"] = {broken.attribute: broken.calls for broken in broken_stops}
        report["broken_stop_cleanups"] = {broken.attribute: broken.cleaned_up for broken in broken_stops}
        report["broken_stop_cancellations_ignored"] = {
            broken.attribute: broken.cancellations_ignored for broken in broken_stops
        }
        report["broken_stop_connections"] = {broken.attribute: broken.connections for broken in broken_stops}
        report["rollback_warnings"] = rollback_warnings
    except Exception as error:  # noqa: BLE001 -- the parent reads the report, whatever happened
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        shutdown_logger.removeHandler(collector)
        patches.undo()
    return report


async def _boot_and_stop(base: Path) -> dict[str, Any]:
    report: dict[str, Any] = {}
    try:
        runtime = make_runtime(base, config=lifecycle_config(base, zero_grace=True))
        await runtime.start()
        report["started"] = runtime._started
        report["yeoman_during"] = YeomanAgent._live_instance_count
        await runtime.stop()
        report["stopped"] = runtime._started is False
        report["yeoman_after"] = YeomanAgent._live_instance_count
    except Exception as error:  # noqa: BLE001
        report["error"] = f"{type(error).__name__}: {error}"
    return report


def _dump() -> Any:
    global _dump_file
    if _dump_file is None:
        _dump_file = open(_HANG_DUMP, "w") if _HANG_DUMP else sys.stderr
    return _dump_file


def _in_its_own_loop(coroutine_function: Any, *args: Any) -> Any:
    runner = asyncio.Runner()
    try:
        return runner.run(coroutine_function(*args))
    finally:
        # Closing a runner cancels and awaits every task still pending, and one that ignores
        # cancellation keeps it from ever returning: cut that short with a dump of every stack
        # instead of waiting for the parent's timeout.
        faulthandler.dump_traceback_later(_SHUTDOWN_WATCHDOG_SECONDS, exit=True, file=_dump())
        runner.close()
        faulthandler.cancel_dump_traceback_later()


def main() -> int:
    install_abortive_self_pipe()  # as conftest does: a closed loop must not pin an ephemeral port
    base = Path.cwd()
    report: dict[str, Any] = {"baseline_yeoman": YeomanAgent._live_instance_count}
    # PROBOS_LIFECYCLE_PHASES is for running one phase per process by hand; the test uses the default.
    phases = [
        phase.strip()
        for phase in os.environ.get("PROBOS_LIFECYCLE_PHASES", "after_infra,finalize_started_event").split(",")
        if phase.strip()
    ]
    with install_codebase_index_memo():
        report["failures"] = [
            _in_its_own_loop(_failed_start, base / phase, phase) for phase in phases
        ]
        report["boot"] = _in_its_own_loop(_boot_and_stop, base / "boot")
    report["main_done_at"] = time.time()
    print("REPORT " + json.dumps(report), flush=True)
    print("MAIN_DONE", flush=True)
    dump = _dump()
    faulthandler.dump_traceback_later(_WATCHDOG_SECONDS, exit=True, file=dump)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.exit(code)
