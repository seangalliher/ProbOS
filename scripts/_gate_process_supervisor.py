#!/usr/bin/env python3
"""Start one gate command only after the parent establishes process containment."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path


def _terminate_child_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _parent_is_alive(process_id: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(synchronize, False, process_id)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _worktree_is_registered(repo_root: Path, gate_root: Path) -> bool:
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if listing.returncode != 0:
        return True
    return any(
        Path(line.removeprefix("worktree ")).resolve() == gate_root.resolve()
        for line in listing.stdout.splitlines()
        if line.startswith("worktree ")
    )


def _cleanup_worktree(repo_root: Path, gate_root: Path) -> bool:
    subprocess.run(
        ["git", "worktree", "remove", "--force", "--force", str(gate_root)],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if gate_root.exists():
        try:
            shutil.rmtree(gate_root)
        except OSError:
            pass
    subprocess.run(
        ["git", "worktree", "prune", "--expire", "now"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return not gate_root.exists() and not _worktree_is_registered(
        repo_root, gate_root
    )


def _watch_worktree(arguments: Sequence[str]) -> int:
    if (
        len(arguments) != 9
        or arguments[0] != "--cleanup-watch"
        or arguments[1] != "--parent-pid"
        or arguments[3] != "--repo-root"
        or arguments[5] != "--gate-root"
        or arguments[7] != "--stop-path"
    ):
        print(
            "gate cleanup watcher requires --cleanup-watch --parent-pid PID "
            "--repo-root PATH --gate-root PATH --stop-path PATH",
            file=sys.stderr,
        )
        return 125
    try:
        parent_pid = int(arguments[2])
    except ValueError:
        print("gate cleanup watcher parent PID is invalid", file=sys.stderr)
        return 125
    repo_root = Path(arguments[4]).resolve()
    gate_root = Path(arguments[6]).resolve()
    stop_path = Path(arguments[8]).resolve()
    try:
        while _parent_is_alive(parent_pid):
            if stop_path.exists():
                action = stop_path.read_text(encoding="utf-8").strip()
                if action == "stop":
                    return 0
                if action == "cleanup":
                    break
            time.sleep(0.1)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if _cleanup_worktree(repo_root, gate_root):
                return 0
            time.sleep(0.1)
        print(
            f"gate cleanup watcher could not remove worktree {gate_root}",
            file=sys.stderr,
        )
        return 125
    finally:
        stop_path.unlink(missing_ok=True)


def main(arguments: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if values and values[0] == "--cleanup-watch":
        return _watch_worktree(values)
    if len(values) < 4 or values[0] != "--parent-pid" or values[2] != "--":
        print(
            "gate process supervisor requires --parent-pid PID -- COMMAND",
            file=sys.stderr,
        )
        return 125
    try:
        parent_pid = int(values[1])
    except ValueError:
        print("gate process supervisor parent PID is invalid", file=sys.stderr)
        return 125
    command = values[3:]
    stdin_fd = sys.stdin.fileno()
    if os.read(stdin_fd, 1) != b"G":
        print("gate process supervisor was not released by its parent", file=sys.stderr)
        return 125
    shutdown_signal: int | None = None

    def request_shutdown(signum: int, _frame: object) -> None:
        nonlocal shutdown_signal
        shutdown_signal = signum

    if os.name != "nt":
        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)

    if shutdown_signal is not None:
        return 128 + shutdown_signal
    process_kwargs: dict[str, object] = {}
    if os.name != "nt":
        process_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        **process_kwargs,
    )

    try:
        while True:
            if shutdown_signal is not None:
                _terminate_child_tree(process)
                process.wait()
                return 128 + shutdown_signal
            exit_code = process.poll()
            if exit_code is not None:
                if os.name != "nt":
                    _terminate_child_tree(process)
                return exit_code
            if not _parent_is_alive(parent_pid):
                _terminate_child_tree(process)
                process.wait()
                return 125
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            _terminate_child_tree(process)
            process.wait()


if __name__ == "__main__":
    raise SystemExit(main())