"""AD-816: pidfile-liveness single-instance guard tests."""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from probos.pidfile_guard import (
    AnotherInstanceRunning,
    _is_pid_alive,
    acquire_pidfile,
    assert_no_other_instance,
)


# ---------- acquire_pidfile ----------


def test_acquire_writes_own_pidfile_when_clean(tmp_path):
    pidfile = acquire_pidfile(tmp_path)
    assert pidfile.exists()
    assert pidfile.read_text().strip() == str(os.getpid())


def test_acquire_treats_stale_pidfile_as_recoverable(tmp_path):
    pf = tmp_path / "probos.pid"
    pf.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    pf.write_text(str(proc.pid))
    acquired = acquire_pidfile(tmp_path)
    assert acquired.read_text().strip() == str(os.getpid())


def test_acquire_raises_when_pidfile_owned_by_live_process(tmp_path):
    pf = tmp_path / "probos.pid"
    pf.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.15)
        pf.write_text(str(proc.pid))
        with pytest.raises(AnotherInstanceRunning) as ei:
            acquire_pidfile(tmp_path)
        assert ei.value.pid == proc.pid
        assert pf.read_text().strip() == str(proc.pid)  # NOT stomped
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_acquire_handles_own_pid_in_stale_pidfile(tmp_path):
    pf = tmp_path / "probos.pid"
    pf.parent.mkdir(exist_ok=True)
    pf.write_text(str(os.getpid()))
    acquired = acquire_pidfile(tmp_path)
    assert acquired.read_text().strip() == str(os.getpid())


def test_acquire_recovers_from_garbage_pidfile(tmp_path):
    pf = tmp_path / "probos.pid"
    pf.parent.mkdir(exist_ok=True)
    pf.write_text("not a number")
    acquired = acquire_pidfile(tmp_path)
    assert acquired.read_text().strip() == str(os.getpid())


def test_acquire_recovers_from_empty_pidfile(tmp_path):
    pf = tmp_path / "probos.pid"
    pf.parent.mkdir(exist_ok=True)
    pf.write_text("")
    acquired = acquire_pidfile(tmp_path)
    assert acquired.read_text().strip() == str(os.getpid())


# ---------- assert_no_other_instance (read-only) ----------


def test_assert_no_pidfile_passes(tmp_path):
    assert_no_other_instance(tmp_path)


def test_assert_raises_when_live(tmp_path):
    pf = tmp_path / "probos.pid"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.15)
        pf.write_text(str(proc.pid))
        with pytest.raises(AnotherInstanceRunning):
            assert_no_other_instance(tmp_path)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_assert_does_not_unlink_live_pidfile(tmp_path):
    pf = tmp_path / "probos.pid"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.15)
        pf.write_text(str(proc.pid))
        with pytest.raises(AnotherInstanceRunning):
            assert_no_other_instance(tmp_path)
        assert pf.exists()
        assert pf.read_text().strip() == str(proc.pid)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ---------- liveness primitives ----------


def test_is_pid_alive_for_own_process():
    assert _is_pid_alive(os.getpid()) is True


def test_is_pid_alive_rejects_invalid_pids():
    assert _is_pid_alive(0) is False
    assert _is_pid_alive(-1) is False


def test_another_instance_error_message_includes_remediation(tmp_path):
    err = AnotherInstanceRunning(
        pid=12345, data_dir=tmp_path, pidfile=tmp_path / "probos.pid"
    )
    msg = str(err)
    assert "12345" in msg
    assert str(tmp_path) in msg
    assert "--data-dir" in msg
