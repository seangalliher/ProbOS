"""pytest-timeout must not leave a finished Timer (two kernel handles) behind per test."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.fixtures import timeout_timer_release as release

REPO_ROOT = Path(__file__).resolve().parent.parent

_NESTED_TESTS = textwrap.dedent(
    """
    import gc
    import threading

    import pytest


    @pytest.mark.parametrize("i", range(6))
    def test_a_noop(i):
        pass


    def test_zz_report_live_timers():
        print("LIVE_TIMERS=%d" % sum(1 for o in gc.get_objects() if isinstance(o, threading.Timer)))
    """
)


def _live_timers_after_six_tests(tmp_path: Path, *extra: str) -> int:
    (tmp_path / "test_nested.py").write_text(_NESTED_TESTS, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT"))}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "test_nested.py", "-q", "-s", "-n", "0", "-p", "no:cacheprovider",
         "-p", "no:randomly", "-o", "addopts=", "-o", "timeout=60", "--rootdir", str(tmp_path), *extra],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    match = re.search(r"LIVE_TIMERS=(\d+)", completed.stdout)
    assert match, completed.stdout
    return int(match.group(1))


def test_wrapper_clears_the_cancel_closure_only_after_the_protocol_ran() -> None:
    item = SimpleNamespace(cancel_timeout=lambda: None)
    protocol = release.pytest_runtest_protocol(item, None)
    next(protocol)
    assert item.cancel_timeout is not None, "the timer must stay armed while the test is running"
    with pytest.raises(StopIteration):
        protocol.send(None)
    assert item.cancel_timeout is None


def test_wrapper_ignores_items_that_never_got_a_timer() -> None:
    item = SimpleNamespace()
    protocol = release.pytest_runtest_protocol(item, None)
    next(protocol)
    with pytest.raises(StopIteration):
        protocol.send(None)
    assert not hasattr(item, "cancel_timeout")


def test_nested_run_without_the_wrapper_keeps_every_finished_timer_alive(tmp_path: Path) -> None:
    assert _live_timers_after_six_tests(tmp_path) >= 6, (
        "control: pytest-timeout no longer retains finished Timers, so the wrapper has nothing left to fix"
    )


def test_nested_run_with_the_wrapper_keeps_no_finished_timer_alive(tmp_path: Path) -> None:
    assert _live_timers_after_six_tests(tmp_path, "-p", "tests.fixtures.timeout_timer_release") <= 1


def test_conftest_wires_the_wrapper_into_the_session() -> None:
    from tests import conftest

    assert conftest.pytest_runtest_protocol is release.pytest_runtest_protocol
