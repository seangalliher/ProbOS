"""Closing an asyncio loop must not pin an ephemeral TCP port in TIME_WAIT (Windows) -- and nothing else changes.

Evidence behind the patch: a 2,874-test single-process run created 2,690 event loops, and 8,070 of the
8,107 Python sockets it opened were their self-pipe ``socketpair`` ends. Each closed loop left one
loopback TIME_WAIT connection for 120 s -- the likely cause of the sporadic ``WinError 10055`` raised in
``connect()`` while a test is being set up, once enough workers (or other test runs on the machine)
churn loops at the same time.

The patch is scoped to asyncio's self-pipe. A socketpair a test creates itself keeps graceful-close
semantics, because an abortive close (RST) discards bytes the reader has not read yet.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import socket
import struct
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from typing import NamedTuple

import pytest

from tests.fixtures import abortive_self_pipe as shim

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="asyncio's self-pipe is a loopback TCP socketpair, and so has a TIME_WAIT, only on Windows",
)
both_loop_kinds = pytest.mark.parametrize("kind", ["proactor", "selector"])

_HOOK = "_make_self_pipe"
_TIME_WAIT = 11
_ABORT_ON_CLOSE = struct.pack("HH", 1, 0)
_GRACEFUL_CLOSE = struct.pack("HH", 0, 0)


class _Built(NamedTuple):
    ends: tuple[socket.socket, socket.socket]
    ports: tuple[int, int]


class _Spy:
    """A real socket's stand-in whose ``setsockopt`` payloads are recorded, and refused for the payloads it is told to."""

    def __init__(self, real: socket.socket, refuse: tuple[bytes, ...] = ()) -> None:
        self.real = real
        self.refuse = refuse
        self.payloads: list[bytes] = []

    def setsockopt(self, level: int, option: int, value: bytes) -> None:
        self.payloads.append(value)
        if value in self.refuse:
            raise OSError("refused")
        self.real.setsockopt(level, option, value)


def _base_loop_class(kind: str) -> type:
    if kind == "proactor":
        from asyncio import proactor_events

        return proactor_events.BaseProactorEventLoop
    from asyncio import selector_events

    return selector_events.BaseSelectorEventLoop


def _new_loop(kind: str) -> asyncio.AbstractEventLoop:
    return asyncio.ProactorEventLoop() if kind == "proactor" else asyncio.SelectorEventLoop()


def _linger(end: socket.socket) -> tuple[int, int]:
    on, seconds = struct.unpack("HH", end.getsockopt(socket.SOL_SOCKET, socket.SO_LINGER, 4))
    return on, seconds


@pytest.fixture
def stock_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both base loop classes with asyncio's own ``_make_self_pipe``, whether or not conftest installed the patch."""
    for kind in ("proactor", "selector"):
        loop_class = _base_loop_class(kind)
        current = getattr(loop_class, _HOOK)
        monkeypatch.setattr(loop_class, _HOOK, getattr(current, "__wrapped__", current))


@contextmanager
def _recording(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[_Built]]:
    """Record every socketpair built while the block runs (a loop builds exactly one: its self-pipe)."""
    built: list[_Built] = []
    build = socket.socketpair

    def recording(*args: object, **kwargs: object) -> tuple[socket.socket, socket.socket]:
        first, second = build(*args, **kwargs)
        built.append(_Built((first, second), (first.getsockname()[1], second.getsockname()[1])))
        return first, second

    with monkeypatch.context() as scoped:
        scoped.setattr(socket, "socketpair", recording)
        yield built


def _self_pipe_lingers(kind: str, monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Build one loop and read ``SO_LINGER`` off both ends of its self-pipe."""
    with _recording(monkeypatch) as built:
        loop = _new_loop(kind)
        try:
            assert len(built) == 1, "building one loop must build exactly one socketpair: its self-pipe"
            return [_linger(end) for end in built[0].ends]
        finally:
            loop.close()


def _time_wait_loopback_pairs() -> set[tuple[int, int]]:
    """(local port, remote port) of every IPv4 loopback TCP connection currently in TIME_WAIT."""
    iphlpapi = ctypes.WinDLL("iphlpapi")
    iphlpapi.GetExtendedTcpTable.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG,
    ]
    iphlpapi.GetExtendedTcpTable.restype = wintypes.DWORD
    for _attempt in range(5):  # the table can grow between sizing it and reading it
        size = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 5, 0)  # AF_INET, TCP_TABLE_OWNER_PID_ALL
        buf = ctypes.create_string_buffer(size.value + 65536)
        size = wintypes.DWORD(len(buf))
        if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 5, 0) == 0:
            break
    else:
        pytest.fail("could not read the TCP table")
    (rows,) = struct.unpack_from("<I", buf.raw, 0)
    found: set[tuple[int, int]] = set()
    for state, laddr, lport, raddr, rport, _pid in struct.iter_unpack("<6I", buf.raw[4 : 4 + 24 * rows]):
        if state == _TIME_WAIT and laddr & 0xFF == 127 and raddr & 0xFF == 127:
            found.add((((lport & 0xFF) << 8) | (lport >> 8 & 0xFF), ((rport & 0xFF) << 8) | (rport >> 8 & 0xFF)))
    return found


def _run_hook_against(first: _Spy, second: _Spy, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the patched selector ``_make_self_pipe`` against a stand-in loop whose self-pipe ends are the spies."""

    def asyncio_hook(loop: types.SimpleNamespace) -> None:
        loop._ssock, loop._csock = first, second

    selector = _base_loop_class("selector")
    monkeypatch.setattr(selector, _HOOK, asyncio_hook)
    with shim.abortive_self_pipe():
        getattr(selector, _HOOK)(types.SimpleNamespace())


def _shim_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == shim.logger.name and r.levelno == logging.WARNING]


def _loops_left_in_time_wait(kind: str, count: int, monkeypatch: pytest.MonkeyPatch) -> int:
    """Create and close ``count`` loops; how many of their self-pipes are now sitting in TIME_WAIT."""
    with _recording(monkeypatch) as built:
        for _ in range(count):
            _new_loop(kind).close()
    assert len(built) == count
    waiting = _time_wait_loopback_pairs()
    return sum(1 for record in built if record.ports in waiting or record.ports[::-1] in waiting)


@windows_only
@both_loop_kinds
def test_a_new_loops_self_pipe_carries_zero_linger_on_both_ends_only_with_the_patch(
    kind: str, stock_loops: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _self_pipe_lingers(kind, monkeypatch) == [(0, 0), (0, 0)], "control: asyncio alone leaves graceful ends"
    with shim.abortive_self_pipe():
        assert _self_pipe_lingers(kind, monkeypatch) == [(1, 0), (1, 0)]


@windows_only
def test_a_plain_socketpair_keeps_graceful_linger_while_loop_self_pipes_are_abortive(
    stock_loops: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with shim.abortive_self_pipe():
        assert _self_pipe_lingers("proactor", monkeypatch) == [(1, 0), (1, 0)], "premise: the patch is active"
        first, second = socket.socketpair()
        try:
            assert [_linger(end)[0] for end in (first, second)] == [0, 0]
        finally:
            first.close()
            second.close()


@windows_only
def test_a_plain_socketpair_still_delivers_bytes_written_before_the_writer_closed(stock_loops: None) -> None:
    hazard_writer, hazard_reader = socket.socketpair()
    hazard_writer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _ABORT_ON_CLOSE)
    hazard_reader.settimeout(5)
    hazard_writer.sendall(b"payload")
    hazard_writer.close()
    with pytest.raises(ConnectionResetError):  # control: an abortive close eats the unread payload
        hazard_reader.recv(16)
    hazard_reader.close()

    with shim.abortive_self_pipe():
        writer, reader = socket.socketpair()
        reader.settimeout(5)
        writer.sendall(b"payload")
        writer.close()
        assert reader.recv(16) == b"payload"
        reader.close()


@windows_only
@both_loop_kinds
def test_closing_loops_leaves_no_time_wait_connection_with_the_patch_and_one_each_without(
    kind: str, stock_loops: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 20
    left_by_stock = _loops_left_in_time_wait(kind, count, monkeypatch)
    assert left_by_stock >= count * 0.9, "control: stock loops must pin a TIME_WAIT port each, or this proves nothing"
    with shim.abortive_self_pipe():
        assert _loops_left_in_time_wait(kind, count, monkeypatch) == 0


@windows_only
def test_install_twice_does_not_stack_wrappers_and_restore_returns_asyncios_own_hook(stock_loops: None) -> None:
    classes = [_base_loop_class(kind) for kind in ("proactor", "selector")]
    stock = [vars(cls)[_HOOK] for cls in classes]
    restore = shim.install_abortive_self_pipe()
    installed = [vars(cls)[_HOOK] for cls in classes]
    assert all(new is not old and new.__wrapped__ is old for new, old in zip(installed, stock))

    second_restore = shim.install_abortive_self_pipe()
    assert [vars(cls)[_HOOK] for cls in classes] == installed, "a second install must be a no-op, not a second wrapper"
    second_restore()
    assert [vars(cls)[_HOOK] for cls in classes] == installed, "undoing a no-op install must not undo the real one"

    restore()
    assert [vars(cls)[_HOOK] for cls in classes] == stock
    restore()
    assert [vars(cls)[_HOOK] for cls in classes] == stock, "restore must be idempotent"


@windows_only
@pytest.mark.parametrize("how", ["missing", "not_callable"])
@pytest.mark.parametrize("broken", ["proactor", "selector"])
def test_a_loop_class_without_a_callable_hook_is_left_unpatched_with_a_warning(
    broken: str, how: str, stock_loops: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    broken_class = _base_loop_class(broken)
    healthy_class = _base_loop_class("selector" if broken == "proactor" else "proactor")
    if how == "missing":
        monkeypatch.delattr(broken_class, _HOOK)
    else:
        monkeypatch.setattr(broken_class, _HOOK, None)
    with caplog.at_level(logging.WARNING, logger=shim.logger.name):
        restore = shim.install_abortive_self_pipe()
    try:
        assert getattr(broken_class, _HOOK, None) is None
        assert hasattr(vars(healthy_class)[_HOOK], "__wrapped__"), "the healthy class must still be patched"
        assert any(broken_class.__name__ in record.getMessage() for record in caplog.records)
    finally:
        restore()


@windows_only
@pytest.mark.parametrize("failure", ["refused", "no_self_pipe"])
def test_a_failed_linger_degrades_to_the_graceful_pair_with_a_warning(
    failure: str, stock_loops: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class RefusesLinger:
        def setsockopt(self, *args: object) -> None:
            raise OSError("refused")

    def asyncio_hook(loop: types.SimpleNamespace) -> None:
        if failure == "refused":
            loop._ssock, loop._csock = RefusesLinger(), RefusesLinger()

    selector = _base_loop_class("selector")
    monkeypatch.setattr(selector, _HOOK, asyncio_hook)
    stand_in = types.SimpleNamespace()
    with caplog.at_level(logging.WARNING, logger=shim.logger.name), shim.abortive_self_pipe():
        getattr(selector, _HOOK)(stand_in)  # the wrapper, run against a stand-in loop
    assert hasattr(stand_in, "_ssock") == (failure == "refused"), "the hook's own work must be left as it built it"
    assert any("SO_LINGER" in record.getMessage() for record in caplog.records)


@windows_only
def test_a_second_end_that_refuses_linger_leaves_both_ends_graceful_with_one_warning(
    stock_loops: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_first, real_second = socket.socketpair()
    first, second = _Spy(real_first), _Spy(real_second, refuse=(_ABORT_ON_CLOSE,))
    try:
        with caplog.at_level(logging.WARNING, logger=shim.logger.name):
            _run_hook_against(first, second, monkeypatch)
        assert first.payloads == [_ABORT_ON_CLOSE, _GRACEFUL_CLOSE], "premise: the first end was switched, then put back"
        assert second.payloads == [_ABORT_ON_CLOSE], "only an end that was switched is put back"
        assert [_linger(end)[0] for end in (real_first, real_second)] == [0, 0]
        assert len(_shim_warnings(caplog)) == 1
    finally:
        real_first.close()
        real_second.close()


@windows_only
def test_a_rollback_that_fails_is_logged_and_the_hook_still_returns(
    stock_loops: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_first, real_second = socket.socketpair()
    first = _Spy(real_first, refuse=(_GRACEFUL_CLOSE,))
    second = _Spy(real_second, refuse=(_ABORT_ON_CLOSE,))
    try:
        with caplog.at_level(logging.WARNING, logger=shim.logger.name):
            _run_hook_against(first, second, monkeypatch)
        assert first.payloads == [_ABORT_ON_CLOSE, _GRACEFUL_CLOSE], "the put-back must still be attempted"
        messages = _shim_warnings(caplog)
        assert len(messages) == 2 and "restore" in messages[1], "the failed put-back must be reported, not hidden"
        assert _linger(real_first) == (1, 0), "premise: the end that could not be put back really is still abortive"
    finally:
        real_first.close()
        real_second.close()


def test_install_off_windows_changes_nothing(stock_loops: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shim, "sys", types.SimpleNamespace(platform="linux"))
    classes = [_base_loop_class(kind) for kind in ("proactor", "selector")]
    before = [vars(cls).get(_HOOK) for cls in classes]
    restore = shim.install_abortive_self_pipe()
    assert [vars(cls).get(_HOOK) for cls in classes] == before
    restore()
    assert [vars(cls).get(_HOOK) for cls in classes] == before


@windows_only
@both_loop_kinds
def test_conftest_installed_the_patch_for_the_whole_session(kind: str) -> None:
    assert hasattr(vars(_base_loop_class(kind))[_HOOK], "__wrapped__"), (
        "tests/conftest.py must install the abortive self-pipe at import, before any test builds a loop"
    )


@windows_only
def test_time_wait_reader_sees_a_plain_socketpair_closed_gracefully() -> None:
    first, second = socket.socketpair()
    pair = (second.getsockname()[1], first.getsockname()[1])
    second.close()  # the end that closes first is the one that enters TIME_WAIT
    first.close()
    assert {pair, pair[::-1]} & _time_wait_loopback_pairs(), "the reader must see a known TIME_WAIT connection"
