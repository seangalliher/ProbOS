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

``PROBOS_LIFECYCLE_BREAK_STEPS`` (comma-separated runtime attributes) makes each named
component's ``stop()`` run and then raise at the moment the injected failure fires, so the
rollback has to go on past a teardown step that fails. The attributes must exist at the
phase under test; the report lists how often each broken ``stop()`` was called.

Exit code 3: probos was imported from somewhere other than ``PROBOS_LIFECYCLE_EXPECT_SRC``.

This module is import-safe: the checks and side effects run only when it is run as a
script. A repository-wide ``git grep`` for consumer tests lists it (it names
``YeomanAgent``), and pytest imports every file it is given.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import os
import sys
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
_BREAK_STEPS = [
    attribute.strip()
    for attribute in os.environ.get("PROBOS_LIFECYCLE_BREAK_STEPS", "").split(",")
    if attribute.strip()
]
_WATCHDOG_SECONDS = 30


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

    def break_the_requested_steps(failing_runtime: Any) -> None:
        broken_stops.extend(break_stop(failing_runtime, attribute) for attribute in _BREAK_STEPS)

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
    except Exception as error:  # noqa: BLE001 -- the parent reads the report, whatever happened
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
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


def _in_its_own_loop(coroutine_function: Any, *args: Any) -> Any:
    with asyncio.Runner() as runner:
        return runner.run(coroutine_function(*args))


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
    print("REPORT " + json.dumps(report), flush=True)
    print("MAIN_DONE", flush=True)
    dump = open(_HANG_DUMP, "w") if _HANG_DUMP else sys.stderr
    faulthandler.dump_traceback_later(_WATCHDOG_SECONDS, exit=True, file=dump)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.exit(code)
