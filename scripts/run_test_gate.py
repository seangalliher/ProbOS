#!/usr/bin/env python3
"""Run the ProbOS Python gate only after cheap deterministic preflight checks."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import locale
import os
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence, TextIO


_BLOCKING_UNTRACKED_PREFIXES = (
    ".github/",
    "config/",
    "desktop/src/",
    "scripts/",
    "src/",
    "tests/",
    "ui/src/",
)
_BLOCKING_UNTRACKED_FILES = frozenset(
    {
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
    }
)
_BLOCKING_UNTRACKED_PYTHON_SUFFIXES = frozenset(
    {".py", ".pyc", ".pyd", ".pyw", ".so"}
)
_IGNORED_EXECUTABLE_ROOTS = ("scripts/", "src/", "tests/")
_ROOT_PYTEST_CONTROL_NAMES = frozenset(
    {
        ".pytest.ini",
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
    }
)
_MUTATION_BACKUP_SUFFIXES = (".mutbak", ".mut_bak", ".mut.bak")
_PYTEST_CONTROL_ENV = frozenset(
    {
        "PROBOS_GATE_COLLECTION_DIR",
        "PYTEST_ADDOPTS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTEST_PLUGINS",
        "PYTHONPYCACHEPREFIX",
        "PYTHONOPTIMIZE",
    }
)
_PYTEST_EXECUTABLE_NAMES = frozenset(
    {"py.test", "py.test.exe", "pytest", "pytest.exe"}
)
_PYTHON_EXECUTABLE_RE = re.compile(
    r"^(?:py|python(?:\d+(?:\.\d+)*)?)(?:\.exe)?$", re.IGNORECASE
)
_SUMMARY_RE = re.compile(
    r"^(?:=+\s*)?(?P<summary>.*\b(?:passed|failed|error|errors)\b.*\bin\s+"
    r"(?:\d+(?:\.\d+)?s|(?:\d+:)?\d{1,2}:\d{2}(?:\.\d+)?))(?:\s*=+)?$",
    re.IGNORECASE | re.MULTILINE,
)
_PYTEST_CONFIG_OVERRIDES = (
    "addopts=",
    "python_files=test_*.py *_test.py",
    "python_classes=Test*",
    "python_functions=test_*",
    "norecursedirs=",
    "junit_family=legacy",
)
_RELEASE_TEST_FILE_EXCLUSIONS = frozenset(
    {
        "tests/ablation/test_sigma_ablation.py",
        "tests/ablation/test_sigma_harness_structural.py",
    }
)


@dataclass(frozen=True)
class TreeSnapshot:
    """Identity of the source tree a gate actually read."""

    head: str
    status_sha256: str
    staged_diff_sha256: str


@dataclass(frozen=True)
class PhaseSpec:
    """One named command in the preflight or full-gate pipeline."""

    name: str
    command: list[str]


@dataclass(frozen=True)
class PhaseResult:
    """Result of one command, retained even when a later phase fails."""

    name: str
    command: list[str]
    elapsed_seconds: float
    exit_code: int


@dataclass(frozen=True)
class JUnitTotals:
    """Validated execution totals from pytest's JUnit report."""

    tests: int
    failures: int
    errors: int
    skipped: int
    time_seconds: float
    extra_reports: int = 0


@dataclass(frozen=True)
class CollectionTotals:
    """Validated collection and execution identity totals."""

    nodes: int
    workers: int
    sha256: str


@dataclass(frozen=True)
class GateResult:
    """Machine-readable record for one preflight or full gate attempt."""

    label: str
    started_at: str
    finished_at: str
    elapsed_seconds: float
    wrapper_exit_code: int
    preflight_exit_code: int | None
    pytest_exit_code: int | None
    preflight_only: bool
    interrupted: bool
    error: str
    tree_changed: bool
    snapshot_before: TreeSnapshot | None
    snapshot_after: TreeSnapshot | None
    command: list[str] | None
    phases: list[PhaseResult]
    sanitized_pytest_environment: list[str]
    summary: str
    log_path: str
    junit_path: str | None
    junit_totals: JUnitTotals | None
    collection_path: str | None
    collection_totals: CollectionTotals | None


class GateLock:
    """Hold an OS lock that the kernel releases if this process dies."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None

    @staticmethod
    def _lock(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __enter__(self) -> "GateLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = self._path.open("x+b")
            handle.write(b"\0")
            handle.flush()
        except FileExistsError:
            handle = self._path.open("r+b")
            if self._path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
        try:
            self._lock(handle)
        except OSError as exc:
            handle.seek(1)
            owner = handle.read().decode("utf-8", errors="replace").strip("\0\r\n ")
            handle.close()
            raise RuntimeError(
                f"Another run_test_gate.py invocation owns {self._path} ({owner})"
            ) from exc
        metadata = f"pid={os.getpid()} started={_utc_now()}\n".encode("utf-8")
        handle.seek(1)
        handle.write(metadata)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is not None:
            self._unlock(self._handle)
            self._handle.close()
            self._handle = None


class _WindowsJob:
    """Kill-on-close Windows Job assigned before the supervised command starts."""

    _KILL_ON_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self, process: subprocess.Popen[str]) -> None:
        import ctypes
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        self._kernel32 = kernel32
        self._handle = handle
        try:
            info = _ExtendedLimitInformation()
            info.BasicLimitInformation.LimitFlags = self._KILL_ON_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                self._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                raise OSError(
                    ctypes.get_last_error(), "SetInformationJobObject failed"
                )
            process_handle = wintypes.HANDLE(int(process._handle))
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise OSError(
                    ctypes.get_last_error(), "AssignProcessToJobObject failed"
                )
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class _ProcessTreeGuard:
    """Contain a blocked supervisor before releasing its child command."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._windows_job = _WindowsJob(process) if os.name == "nt" else None
        self._closed = False

    def release(self) -> None:
        if self._process.stdin is None:
            raise RuntimeError("Gate process supervisor has no release pipe")
        self._process.stdin.write("G")
        self._process.stdin.flush()
        self._process.stdin.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        if self._windows_job is not None:
            self._windows_job.close()
            return
        _terminate_posix_process_group(self._process.pid)


def _terminate_posix_process_group(process_group_id: int) -> None:
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify_label(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "gate"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _status_lines_sha256(repo_root: Path) -> str:
    status = _git_bytes(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).decode("utf-8", errors="strict")
    canonical = "\n".join(status.splitlines()).encode("utf-8")
    return _sha256(canonical)


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _git_common_dir(repo_root: Path) -> Path:
    raw = _git_bytes(repo_root, "rev-parse", "--git-common-dir").decode().strip()
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _gate_lock_path(repo_root: Path) -> Path:
    return _git_common_dir(repo_root) / "probos-test-gate.lock"


def _artifact_paths(
    repo_root: Path, *, label: str, head: str
) -> tuple[Path, Path, Path]:
    artifact_dir = repo_root / "logs" / "gates"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    nonce = uuid.uuid4().hex[:8]
    stem = f"{timestamp}-{label}-{head}-p{os.getpid()}-{nonce}"
    return (
        artifact_dir / f"{stem}.log",
        artifact_dir / f"{stem}.xml",
        artifact_dir / f"{stem}.json",
    )


def _snapshot_tree(repo_root: Path) -> TreeSnapshot:
    head = _git_bytes(repo_root, "rev-parse", "HEAD").decode().strip()
    status = _git_bytes(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    staged = _git_bytes(repo_root, "diff", "--cached", "--binary", "--no-ext-diff")
    return TreeSnapshot(
        head=head,
        status_sha256=_sha256(status),
        staged_diff_sha256=_sha256(staged),
    )


def _committed_tree_error(repo_root: Path) -> str | None:
    head_tree = _git_bytes(repo_root, "rev-parse", "HEAD^{tree}").decode().strip()
    index_tree = _git_bytes(repo_root, "write-tree").decode().strip()
    if head_tree == index_tree:
        return None
    return (
        "Full gate requires a committed tree: the Git index differs from HEAD. "
        "Commit the reviewed changes before running release validation."
    )


def _remove_materialized_gate_tree(repo_root: Path, gate_root: Path) -> str | None:
    failures: list[str] = []
    for _ in range(2):
        cleanup = subprocess.run(
            [
                "git",
                "worktree",
                "remove",
                "--force",
                "--force",
                str(gate_root),
            ],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cleanup.returncode == 0:
            break
        detail = cleanup.stderr.strip() or cleanup.stdout.strip()
        failures.append(f"git worktree remove exited {cleanup.returncode}: {detail}")
    if gate_root.exists():
        try:
            shutil.rmtree(gate_root)
        except OSError as exc:
            failures.append(f"directory removal failed: {exc}")
    prune = subprocess.run(
        ["git", "worktree", "prune", "--expire", "now"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if prune.returncode != 0:
        detail = prune.stderr.strip() or prune.stdout.strip()
        failures.append(f"git worktree prune exited {prune.returncode}: {detail}")
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
        detail = listing.stderr.strip() or listing.stdout.strip()
        failures.append(f"git worktree list exited {listing.returncode}: {detail}")
        registered = True
    else:
        registered = any(
            Path(line.removeprefix("worktree ")).resolve() == gate_root.resolve()
            for line in listing.stdout.splitlines()
            if line.startswith("worktree ")
        )
    if gate_root.exists():
        failures.append(f"materialized directory still exists: {gate_root}")
    if registered:
        failures.append(f"materialized worktree is still registered: {gate_root}")
    if gate_root.exists() or registered:
        return " | ".join(failures)
    return None


def _start_worktree_janitor(
    repo_root: Path, gate_root: Path
) -> tuple[subprocess.Popen[bytes], Path]:
    common_dir = _git_common_dir(repo_root)
    stop_path = common_dir / f"probos-gate-janitor-{uuid.uuid4().hex}.control"
    stop_path.unlink(missing_ok=True)
    supervisor = Path(__file__).with_name("_gate_process_supervisor.py")
    process_kwargs: dict[str, object] = {}
    if os.name == "nt":
        process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        [
            sys.executable,
            str(supervisor),
            "--cleanup-watch",
            "--parent-pid",
            str(os.getpid()),
            "--repo-root",
            str(repo_root),
            "--gate-root",
            str(gate_root),
            "--stop-path",
            str(stop_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **process_kwargs,
    )
    return process, stop_path


def _finish_worktree_janitor(
    process: subprocess.Popen[bytes], stop_path: Path, *, cleanup: bool
) -> str | None:
    try:
        stop_path.write_text("cleanup" if cleanup else "stop", encoding="utf-8")
        try:
            exit_code = process.wait(timeout=35 if cleanup else 10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            return "worktree cleanup watcher did not terminate"
        if exit_code != 0:
            return f"worktree cleanup watcher exited {exit_code}"
        return None
    finally:
        stop_path.unlink(missing_ok=True)


@contextmanager
def _materialized_gate_tree(
    repo_root: Path, expected: TreeSnapshot
) -> Iterator[Path]:
    patch = _git_bytes(
        repo_root,
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--no-ext-diff",
    )
    gate_root = Path(
        tempfile.mkdtemp(prefix=".probos-gate-", dir=repo_root.parent)
    )
    gate_root.rmdir()
    janitor, janitor_stop_path = _start_worktree_janitor(repo_root, gate_root)
    added = False
    active_error: BaseException | None = None
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", "--quiet", str(gate_root), expected.head],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        added = True
        if patch:
            subprocess.run(
                ["git", "apply", "--index", "--binary", "--whitespace=nowarn", "-"],
                cwd=gate_root,
                input=patch,
                check=True,
                capture_output=True,
            )
        actual = _snapshot_tree(gate_root)
        if (
            actual.head != expected.head
            or actual.staged_diff_sha256 != expected.staged_diff_sha256
        ):
            raise RuntimeError(
                "Materialized gate tree does not match the admitted HEAD and index"
            )
        yield gate_root
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        if added:
            cleanup_error = _remove_materialized_gate_tree(repo_root, gate_root)
            janitor_error = _finish_worktree_janitor(
                janitor, janitor_stop_path, cleanup=cleanup_error is not None
            )
            if cleanup_error is not None and janitor_error is None:
                cleanup_error = _remove_materialized_gate_tree(repo_root, gate_root)
            if janitor_error:
                cleanup_error = (
                    f"{cleanup_error} | {janitor_error}"
                    if cleanup_error
                    else janitor_error
                )
            if cleanup_error:
                message = f"Unable to remove materialized gate tree: {cleanup_error}"
                if active_error is not None:
                    active_error.add_note(message)
                else:
                    raise RuntimeError(message)
        elif gate_root.exists():
            shutil.rmtree(gate_root, ignore_errors=True)
            _finish_worktree_janitor(janitor, janitor_stop_path, cleanup=False)
        else:
            _finish_worktree_janitor(janitor, janitor_stop_path, cleanup=False)


def _blocking_worktree_errors(repo_root: Path) -> list[str]:
    errors: list[str] = []
    unstaged = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff"],
        cwd=repo_root,
        check=False,
    )
    if unstaged.returncode == 1:
        errors.append(
            "Tracked unstaged changes are present; stage the intended gate tree or "
            "use an isolated worktree."
        )
    elif unstaged.returncode != 0:
        errors.append(f"git diff --quiet failed with exit code {unstaged.returncode}.")

    whitespace = subprocess.run(
        ["git", "diff", "--cached", "--check"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if whitespace.returncode != 0:
        detail = whitespace.stdout.strip() or whitespace.stderr.strip()
        errors.append(f"Staged diff whitespace check failed: {detail}")

    untracked = [
        item.decode("utf-8", errors="replace")
        for item in _git_bytes(
            repo_root, "ls-files", "--others", "--exclude-standard", "-z"
        ).split(b"\0")
        if item
    ]
    blocking_untracked = [
        path
        for path in untracked
        if path.replace("\\", "/") in _BLOCKING_UNTRACKED_FILES
        or path.replace("\\", "/").startswith(_BLOCKING_UNTRACKED_PREFIXES)
        or Path(path).suffix.lower() in _BLOCKING_UNTRACKED_PYTHON_SUFFIXES
    ]
    if blocking_untracked:
        errors.append(
            "Untracked code, tests, configuration, or workflow files would make the "
            f"gate uncommittable: {', '.join(blocking_untracked[:12])}"
        )
    blocking_untracked_set = set(blocking_untracked)

    tracked_root = {
        item.decode("utf-8", errors="replace")
        for item in _git_bytes(repo_root, "ls-files", "-z", "--", "*").split(b"\0")
        if item and b"/" not in item and b"\\" not in item
    }
    hidden_root_inputs: list[str] = []
    for path in repo_root.iterdir():
        if path.name in {".git", ".venv"}:
            continue
        if path.is_file() and (
            path.name in _ROOT_PYTEST_CONTROL_NAMES
            or path.suffix.lower() in _BLOCKING_UNTRACKED_PYTHON_SUFFIXES
        ):
            if path.name not in tracked_root and path.name not in blocking_untracked_set:
                hidden_root_inputs.append(path.name)
        elif path.is_dir() and (path / "__init__.py").is_file():
            init_path = f"{path.name}/__init__.py"
            tracked_init = _git_bytes(
                repo_root, "ls-files", "-z", "--", init_path
            )
            if not tracked_init:
                hidden_root_inputs.append(init_path)
    if hidden_root_inputs:
        errors.append(
            "Untracked or ignored root Python/pytest inputs can alter collection: "
            + ", ".join(sorted(hidden_root_inputs)[:12])
        )

    ignored = [
        item.decode("utf-8", errors="replace").replace("\\", "/")
        for item in _git_bytes(
            repo_root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        ).split(b"\0")
        if item
    ]
    ignored_executable_inputs = []
    for path in ignored:
        relative = Path(path)
        suffix = relative.suffix.lower()
        is_sourceless_cache = suffix == ".pyc" and "__pycache__" not in relative.parts
        if path.startswith(_IGNORED_EXECUTABLE_ROOTS) and (
            relative.name in _ROOT_PYTEST_CONTROL_NAMES
            or suffix in {".py", ".pyd", ".pyw", ".so"}
            or is_sourceless_cache
        ):
            ignored_executable_inputs.append(path)
    if ignored_executable_inputs:
        errors.append(
            "Ignored Python/pytest inputs under executable roots can alter the gate: "
            + ", ".join(sorted(ignored_executable_inputs)[:12])
        )

    mutation_backups: list[str] = []
    for root_name in ("src", "tests", "scripts", "ui/src"):
        root = repo_root / root_name
        if not root.is_dir():
            continue
        mutation_backups.extend(
            str(path.relative_to(repo_root))
            for path in root.rglob("*")
            if path.is_file() and path.name.endswith(_MUTATION_BACKUP_SUFFIXES)
        )
    if mutation_backups:
        errors.append(
            "Mutation backup files remain in the gate tree: "
            + ", ".join(mutation_backups[:12])
        )
    return errors


def _subprocess_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in _PYTEST_CONTROL_ENV:
        env.pop(name, None)
    env.pop("PYTHONHOME", None)
    source_root = str((repo_root / "src").resolve())
    env["PYTHONPATH"] = source_root
    env["PROBOS_PYTHON"] = sys.executable
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _pytest_subprocess_env(
    repo_root: Path, collection_dir: Path
) -> dict[str, str]:
    env = _subprocess_env(repo_root)
    site_packages = str(Path(sysconfig.get_paths()["purelib"]).resolve())
    source_root = str((repo_root / "src").resolve())
    env["PYTHONPATH"] = os.pathsep.join(
        (site_packages, str(repo_root.resolve()), source_root)
    )
    env["PROBOS_GATE_COLLECTION_DIR"] = str(collection_dir.resolve())
    env["PYTHONPYCACHEPREFIX"] = str((collection_dir / "pycache").resolve())
    return env


def _command_tokens(command_line: str) -> list[str]:
    return [
        quoted or bare
        for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', command_line)
        if quoted or bare
    ]


def _is_pytest_process(process_name: str, command_line: str) -> bool:
    name = Path(process_name.strip('"')).name.lower()
    if name in _PYTEST_EXECUTABLE_NAMES:
        return True
    if not _PYTHON_EXECUTABLE_RE.fullmatch(name):
        return False

    tokens = _command_tokens(command_line)
    for index, token in enumerate(tokens):
        normalized = token.strip('"').lower()
        if normalized == "-m" and index + 1 < len(tokens):
            if tokens[index + 1].strip('"').lower() in {"pytest", "py.test"}:
                return True
    return len(tokens) > 1 and Path(tokens[1].strip('"').lower()).name in (
        _PYTEST_EXECUTABLE_NAMES
    )


def _parse_pytest_process_lines(output: str, *, own_pid: int) -> list[str]:
    processes: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.count("\t") < 2:
            continue
        pid_text, process_name, command_line = line.split("\t", 2)
        try:
            process_id = int(pid_text.strip())
        except ValueError:
            continue
        if process_id == own_pid:
            continue
        if _is_pytest_process(process_name, command_line):
            processes.append(
                f"pid={process_id} name={process_name.strip()} "
                f"command={command_line.strip()}"
            )
    return processes


def _running_pytest_processes() -> list[str]:
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match "
            "'^(?:py|python(?:\\d+(?:\\.\\d+)*)?|py\\.test|pytest)(?:\\.exe)?$' } | "
            "ForEach-Object { "
            "\"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }",
        ]
    else:
        command = ["ps", "-eo", "pid=,comm=,args="]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Unable to enumerate running pytest processes (exit {completed.returncode})"
        )

    if os.name != "nt":
        normalized_lines: list[str] = []
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(maxsplit=2)
            if len(parts) == 3:
                normalized_lines.append(f"{parts[0]}\t{parts[1]}\t{parts[2]}")
        output = "\n".join(normalized_lines)
    else:
        output = completed.stdout
    return _parse_pytest_process_lines(output, own_pid=os.getpid())


def _display_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


def _write_console(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding)
    sys.stdout.write(safe_text)
    sys.stdout.flush()

def _exception_text(exc: BaseException) -> str:
    parts = [str(exc)]
    parts.extend(str(note) for note in getattr(exc, "__notes__", []))
    return " | ".join(part for part in parts if part)


def _run_streaming_command(
    command: Sequence[str],
    *,
    cwd: Path,
    log: TextIO,
    env: dict[str, str],
    supervisor: Path | None = None,
) -> int:
    heading = f"$ {_display_command(command)}\n"
    _write_console(heading)
    log.write(heading)
    log.flush()

    supervisor = supervisor or Path(__file__).with_name("_gate_process_supervisor.py")
    if not supervisor.is_file():
        raise RuntimeError(f"Gate process supervisor is missing: {supervisor}")
    process_kwargs: dict[str, object] = {}
    if os.name == "nt":
        process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        [
            sys.executable,
            str(supervisor),
            "--parent-pid",
            str(os.getpid()),
            "--",
            *command,
        ],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        bufsize=1,
        env=env,
        **process_kwargs,
    )
    if process.stdout is None:
        raise RuntimeError("Gate subprocess did not expose stdout")
    guard: _ProcessTreeGuard | None = None
    reader_error: list[BaseException] = []

    def copy_output() -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                _write_console(line)
                log.write(line)
                log.flush()
        except BaseException as exc:
            reader_error.append(exc)

    reader = threading.Thread(target=copy_output, name="gate-output")
    try:
        guard = _ProcessTreeGuard(process)
        reader.start()
        guard.release()
        while process.poll() is None:
            if reader_error:
                raise RuntimeError(f"Gate output reader failed: {reader_error[0]}")
            time.sleep(0.05)
        exit_code = process.returncode
        guard.close()
        reader.join(timeout=10)
        if reader.is_alive():
            raise RuntimeError("Gate output reader did not terminate after cleanup")
        if reader_error:
            raise RuntimeError(f"Gate output reader failed: {reader_error[0]}")
        process.stdout.close()
        return exit_code
    except BaseException:
        if guard is not None:
            guard.close()
        else:
            _terminate_process_tree(process)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        if reader.is_alive():
            reader.join(timeout=10)
        process.stdout.close()
        raise


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate a command and every descendant before releasing the gate lock."""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def _staged_prompt_paths(repo_root: Path) -> list[str]:
    raw = _git_bytes(
        repo_root,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
    )
    paths = [
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in raw.split(b"\0")
        if item
    ]
    return [
        path
        for path in paths
        if path.startswith("prompts/")
        and path.endswith(".md")
        and (repo_root / path).is_file()
    ]


def _preflight_specs(repo_root: Path) -> list[PhaseSpec]:
    python = sys.executable
    expected_source = json.dumps(str((repo_root / "src").resolve()))
    origin_probe = (
        "from pathlib import Path; import probos; "
        f"expected=Path({expected_source}); actual=Path(probos.__file__).resolve(); "
        "print(f'probos import: {actual}'); "
        "raise SystemExit(0 if actual.is_relative_to(expected) else 2)"
    )
    specs = [
        PhaseSpec("import-origin", [python, "-P", "-c", origin_probe]),
        PhaseSpec(
            "config-reference",
            [python, "-P", "scripts/gen_config_reference.py", "--check"],
        ),
        PhaseSpec(
            "config-profiles",
            [python, "-P", "scripts/check_config_profiles.py", "--check"],
        ),
        PhaseSpec(
            "config-facade",
            [python, "-P", "scripts/check_config_facade.py", "--check"],
        ),
        PhaseSpec(
            "ad-ledger", [python, "-P", "scripts/gen_ad_ledger.py", "--check"]
        ),
        PhaseSpec(
            "seam-contracts",
            [python, "-P", "scripts/check_seam_contracts.py", "--check"],
        ),
        PhaseSpec(
            "architecture-fitness",
            [python, "-P", "scripts/check_architecture_principles.py", "--check"],
        ),
        PhaseSpec(
            "store-registry",
            [python, "-P", "scripts/check_store_registry.py", "--check"],
        ),
        PhaseSpec(
            "compile",
            [python, "-P", "-m", "compileall", "-q", "-j", "0", "src", "tests"],
        ),
    ]
    prompts = _staged_prompt_paths(repo_root)
    if prompts:
        powershell = shutil.which("pwsh")
        if not powershell:
            raise RuntimeError(
                "Staged prompts require PowerShell 7 (pwsh) for UTF-8-safe "
                "phantom-api-precheck.ps1 execution"
            )
        specs.append(
            PhaseSpec(
                "phantom-api",
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(repo_root / "scripts" / "phantom-api-precheck.ps1"),
                    *prompts,
                ],
            )
        )
    return specs


def _build_full_command(
    *,
    repo_root: Path,
    junit_path: Path,
    workers: int,
    distribution: str,
) -> list[str]:
    gate_root = json.dumps(str(repo_root.resolve()))
    source_root = json.dumps(str((repo_root / "src").resolve()))
    bootstrap = (
        "import sys, sysconfig\n"
        "from pathlib import Path\n"
        "trusted_roots = (Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve())\n"
        "sys.path[:] = [entry for entry in sys.path if entry and any("
        "Path(entry).resolve().is_relative_to(root) for root in trusted_roots)]\n"
        "import pytest\n"
        "origin = Path(pytest.__file__).resolve()\n"
        "site_packages = Path(sysconfig.get_paths()['purelib']).resolve()\n"
        "print(f'pytest import: {origin}')\n"
        "if not origin.is_relative_to(site_packages):\n"
        "    print('pytest did not resolve from the selected interpreter site-packages', "
        "file=sys.stderr)\n"
        "    raise SystemExit(5)\n"
        f"sys.path[:0] = [{gate_root}, {source_root}]\n"
        "raise SystemExit(pytest.console_main())\n"
    )
    command = [
        sys.executable,
        "-I",
        "-c",
        bootstrap,
        "tests/",
        "-q",
        "-p",
        "scripts._gate_pytest_plugin",
        "-n",
        str(workers),
        f"--dist={distribution}",
        "--durations=50",
        f"--junitxml={junit_path}",
    ]
    for override in _PYTEST_CONFIG_OVERRIDES:
        command.extend(("-o", override))
    return command


def _tracked_test_census(repo_root: Path) -> set[str]:
    paths = [
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in _git_bytes(repo_root, "ls-files", "-z", "--", "tests").split(
            b"\0"
        )
        if item
    ]
    census: set[str] = set()
    for relative in paths:
        if relative in _RELEASE_TEST_FILE_EXCLUSIONS:
            continue
        name = Path(relative).name
        if not (
            fnmatch.fnmatchcase(name, "test_*.py")
            or fnmatch.fnmatchcase(name, "*_test.py")
        ):
            continue
        tree = ast.parse((repo_root / relative).read_text(encoding="utf-8"))
        declares_test = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
        if declares_test:
            census.add(relative)
    return census


def _node_digest(values: Sequence[str]) -> str:
    payload = json.dumps(
        tuple(values), ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(payload)


def _validate_collection_manifests(
    collection_dir: Path,
    artifact_path: Path,
    *,
    expected_workers: int,
    required_test_files: set[str],
    junit_totals: JUnitTotals,
) -> CollectionTotals:
    paths = sorted(collection_dir.glob("gw*.json"))
    expected_ids = {f"gw{index}" for index in range(expected_workers)}
    actual_ids = {path.stem for path in paths}
    if actual_ids != expected_ids:
        raise RuntimeError(
            "pytest collection evidence has unexpected workers: "
            f"expected={sorted(expected_ids)} actual={sorted(actual_ids)}"
        )
    manifests: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"pytest collection evidence is unreadable: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise RuntimeError(f"pytest collection evidence has invalid schema: {path}")
        if payload.get("worker_id") != path.stem:
            raise RuntimeError(f"pytest collection worker identity mismatch: {path}")
        if payload.get("exitstatus") != 0:
            raise RuntimeError(
                f"pytest collection worker {path.stem} exited nonzero"
            )
        manifests[path.stem] = payload

    primary = manifests["gw0"]
    collected = primary.get("collected_nodeids")
    collected_files = primary.get("collected_files")
    if (
        not isinstance(collected, list)
        or not all(isinstance(node, str) for node in collected)
        or not isinstance(collected_files, list)
        or not all(isinstance(path, str) for path in collected_files)
    ):
        raise RuntimeError("pytest primary collection evidence is incomplete")
    if collected != sorted(collected) or len(collected) != len(set(collected)):
        raise RuntimeError("pytest primary collection node IDs are not canonical")
    collection_sha256 = _node_digest(collected)
    for worker_id, payload in manifests.items():
        if (
            payload.get("collection_count") != len(collected)
            or payload.get("collection_sha256") != collection_sha256
        ):
            raise RuntimeError(
                f"pytest worker {worker_id} collected a different node set"
            )
        removed = payload.get("removed_nodeids")
        added = payload.get("added_nodeids")
        if (
            payload.get("final_count") != len(collected)
            or payload.get("final_sha256") != collection_sha256
            or removed
            or added
        ):
            raise RuntimeError(
                "canonical gate forbids collection item changes: "
                f"worker={worker_id} removed={removed} added={added}"
            )

    missing_files = sorted(
        required_test_files
        - {str(path).replace("\\", "/").removeprefix("./") for path in collected_files}
    )
    if missing_files:
        raise RuntimeError(
            "pytest collection omitted required release test files: "
            + ", ".join(missing_files[:12])
        )

    executed: set[str] = set()
    worker_counts: dict[str, int] = {}
    for worker_id, payload in manifests.items():
        worker_nodes = payload.get("executed_nodeids")
        if (
            not isinstance(worker_nodes, list)
            or not all(isinstance(node, str) for node in worker_nodes)
            or len(worker_nodes) != len(set(worker_nodes))
        ):
            raise RuntimeError(
                f"pytest worker {worker_id} execution evidence is invalid"
            )
        duplicates = executed.intersection(worker_nodes)
        if duplicates:
            raise RuntimeError(
                "pytest executed node IDs more than once across workers: "
                + ", ".join(sorted(duplicates)[:8])
            )
        executed.update(worker_nodes)
        worker_counts[worker_id] = len(worker_nodes)
    collected_set = set(collected)
    if executed != collected_set:
        missing = sorted(collected_set - executed)
        unexpected = sorted(executed - collected_set)
        raise RuntimeError(
            "pytest execution does not match protected collection: "
            f"missing={missing[:8]} unexpected={unexpected[:8]}"
        )
    if junit_totals.tests != len(collected):
        raise RuntimeError(
            "pytest JUnit total does not match protected collection: "
            f"junit={junit_totals.tests} collected={len(collected)}"
        )

    artifact = {
        "schema_version": 1,
        "collection_count": len(collected),
        "collection_sha256": collection_sha256,
        "collected_nodeids": collected,
        "collected_files": collected_files,
        "executed_nodeids": sorted(executed),
        "worker_execution_counts": worker_counts,
    }
    temporary = artifact_path.with_name(
        f".{artifact_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, artifact_path)
    finally:
        temporary.unlink(missing_ok=True)
    return CollectionTotals(
        nodes=len(collected),
        workers=expected_workers,
        sha256=collection_sha256,
    )


def _extract_summary(log_text: str) -> str:
    matches = list(_SUMMARY_RE.finditer(log_text))
    return matches[-1].group("summary").strip() if matches else ""


def _xml_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _parse_junit(
    path: Path, *, required_test_files: set[str] | None = None
) -> JUnitTotals:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"pytest exited 0 without a nonempty JUnit report: {path}")
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise RuntimeError(f"pytest JUnit report is unreadable: {path}: {exc}") from exc

    if _xml_tag(root) == "testsuite":
        suites = [root]
    elif _xml_tag(root) == "testsuites":
        suites = [child for child in root if _xml_tag(child) == "testsuite"]
    else:
        raise RuntimeError(f"pytest JUnit report has unexpected root: {root.tag}")
    if not suites:
        raise RuntimeError(f"pytest JUnit report contains no test suites: {path}")

    def integer(element: ET.Element, name: str) -> int:
        try:
            return int(element.attrib.get(name, "0"))
        except ValueError as exc:
            raise RuntimeError(f"pytest JUnit {name} is not an integer") from exc

    def duration(element: ET.Element) -> float:
        try:
            return float(element.attrib.get("time", "0"))
        except ValueError as exc:
            raise RuntimeError("pytest JUnit time is not numeric") from exc

    declared_tests = sum(integer(suite, "tests") for suite in suites)
    failures = sum(integer(suite, "failures") for suite in suites)
    errors = sum(integer(suite, "errors") for suite in suites)
    skipped = sum(integer(suite, "skipped") for suite in suites)
    testcases = [
        element
        for suite in suites
        for element in suite.iter()
        if _xml_tag(element) == "testcase"
    ]
    testcase_count = len(testcases)
    if declared_tests < testcase_count:
        raise RuntimeError(
            "pytest JUnit declared "
            f"{declared_tests} tests but contains {testcase_count} testcase records"
        )
    totals = JUnitTotals(
        tests=testcase_count,
        failures=failures,
        errors=errors,
        skipped=skipped,
        time_seconds=sum(duration(suite) for suite in suites),
        extra_reports=declared_tests - testcase_count,
    )
    if min(
        totals.tests,
        totals.failures,
        totals.errors,
        totals.skipped,
    ) < 0:
        raise RuntimeError("pytest JUnit report contains a negative count")
    classified = totals.failures + totals.errors + totals.skipped
    if classified > totals.tests:
        raise RuntimeError(
            "pytest JUnit report categories exceed its total test count"
        )
    if totals.tests - totals.skipped <= 0:
        raise RuntimeError("pytest JUnit report contains zero executed tests")
    actual_outcomes = {"failures": 0, "errors": 0, "skipped": 0}
    observed_test_files: set[str] = set()
    for testcase in testcases:
        outcomes = [
            _xml_tag(child)
            for child in testcase
            if _xml_tag(child) in {"failure", "error", "skipped"}
        ]
        if len(outcomes) > 1:
            raise RuntimeError(
                "pytest JUnit testcase contains multiple terminal outcomes"
            )
        if outcomes:
            key = {
                "failure": "failures",
                "error": "errors",
                "skipped": "skipped",
            }[outcomes[0]]
            actual_outcomes[key] += 1
        file_name = testcase.attrib.get("file")
        if file_name:
            observed_test_files.add(file_name.replace("\\", "/").removeprefix("./"))
    declared_outcomes = {
        "failures": totals.failures,
        "errors": totals.errors,
        "skipped": totals.skipped,
    }
    if actual_outcomes != declared_outcomes:
        raise RuntimeError(
            "pytest JUnit outcome counters disagree with testcase records: "
            f"declared={declared_outcomes} actual={actual_outcomes}"
        )
    if required_test_files is not None:
        missing_test_files = sorted(required_test_files - observed_test_files)
        if missing_test_files:
            raise RuntimeError(
                "pytest JUnit omitted tracked test files from the collection census: "
                + ", ".join(missing_test_files[:12])
            )
    return totals


def _write_manifest(path: Path, result: GateResult) -> None:
    path.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_success_receipt(
    path: Path,
    *,
    repo_root: Path,
    result: GateResult,
    source_snapshot: TreeSnapshot,
    manifest_path: Path,
    junit_path: Path,
    collection_path: Path,
) -> None:
    if result.wrapper_exit_code != 0:
        raise RuntimeError("Cannot issue a success receipt for a failed gate")
    if result.preflight_only or result.preflight_exit_code != 0:
        raise RuntimeError("Cannot issue a success receipt without full preflight")
    if result.pytest_exit_code != 0 or result.junit_totals is None:
        raise RuntimeError("Cannot issue a success receipt without successful pytest")
    if result.collection_totals is None or not collection_path.is_file():
        raise RuntimeError("Cannot issue a success receipt without collection evidence")
    head_tree = _git_bytes(repo_root, "rev-parse", "HEAD^{tree}").decode().strip()
    index_tree = _git_bytes(repo_root, "write-tree").decode().strip()
    if head_tree != index_tree:
        raise RuntimeError("Cannot issue a success receipt for an uncommitted index")
    payload = {
        "schema_version": 1,
        "label": result.label,
        "finished_at": result.finished_at,
        "status": {
            "wrapper_exit_code": result.wrapper_exit_code,
            "preflight_exit_code": result.preflight_exit_code,
            "pytest_exit_code": result.pytest_exit_code,
            "preflight_only": result.preflight_only,
            "tree_changed": result.tree_changed,
        },
        "tree": {
            "head": source_snapshot.head,
            "head_tree": head_tree,
            "index_tree": index_tree,
            "status_sha256": _status_lines_sha256(repo_root),
            "raw_status_sha256": source_snapshot.status_sha256,
            "staged_diff_sha256": source_snapshot.staged_diff_sha256,
        },
        "manifest": {
            "path": str(manifest_path.relative_to(repo_root)).replace("\\", "/"),
            "sha256": _sha256_file(manifest_path),
        },
        "junit": {
            "path": str(junit_path.relative_to(repo_root)).replace("\\", "/"),
            "sha256": _sha256_file(junit_path),
            "totals": asdict(result.junit_totals),
        },
        "collection": {
            "path": str(collection_path.relative_to(repo_root)).replace("\\", "/"),
            "sha256": _sha256_file(collection_path),
            "totals": asdict(result.collection_totals),
        },
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _execute_phase(
    spec: PhaseSpec,
    *,
    cwd: Path,
    log: TextIO,
    env: dict[str, str],
    results: list[PhaseResult],
) -> int:
    started = time.monotonic()
    try:
        exit_code = _run_streaming_command(
            spec.command,
            cwd=cwd,
            log=log,
            env=env,
            supervisor=cwd / "scripts" / "_gate_process_supervisor.py",
        )
    except KeyboardInterrupt:
        results.append(
            PhaseResult(
                name=spec.name,
                command=spec.command,
                elapsed_seconds=round(time.monotonic() - started, 3),
                exit_code=130,
            )
        )
        raise
    except Exception:
        results.append(
            PhaseResult(
                name=spec.name,
                command=spec.command,
                elapsed_seconds=round(time.monotonic() - started, 3),
                exit_code=5,
            )
        )
        raise
    results.append(
        PhaseResult(
            name=spec.name,
            command=spec.command,
            elapsed_seconds=round(time.monotonic() - started, 3),
            exit_code=exit_code,
        )
    )
    return exit_code


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="gate")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--dist", choices=("loadfile", "loadscope", "worksteal"), default="loadfile"
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_args(arguments)
    repo_root = args.repo_root.resolve()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if not (repo_root / ".git").exists():
        raise SystemExit(f"Not a Git worktree: {repo_root}")
    if args.receipt and args.preflight_only:
        raise SystemExit("--receipt requires a full gate, not --preflight-only")

    label = _slugify_label(args.label)
    head = _git_bytes(repo_root, "rev-parse", "--short=12", "HEAD").decode().strip()
    log_path, junit_path, manifest_path = _artifact_paths(
        repo_root, label=label, head=head
    )
    collection_dir = junit_path.with_suffix(".collection-workers")
    collection_path = junit_path.with_suffix(".collection.json")
    receipt_path: Path | None = None
    if args.receipt:
        receipt_path = (
            args.receipt.resolve()
            if args.receipt.is_absolute()
            else (repo_root / args.receipt).resolve()
        )
        receipt_root = (repo_root / "logs" / "gates").resolve()
        if not receipt_path.is_relative_to(receipt_root):
            raise SystemExit("--receipt must be inside the repository logs/gates directory")
        if receipt_path.exists():
            raise SystemExit(f"Success receipt already exists: {receipt_path}")
    lock_path = _gate_lock_path(repo_root)

    started_at = _utc_now()
    started = time.monotonic()
    wrapper_exit_code = 5
    preflight_exit_code: int | None = None
    pytest_exit_code: int | None = None
    interrupted = False
    error = ""
    tree_changed = False
    snapshot_before: TreeSnapshot | None = None
    snapshot_after: TreeSnapshot | None = None
    source_snapshot_before: TreeSnapshot | None = None
    source_snapshot_after: TreeSnapshot | None = None
    full_command: list[str] | None = None
    phases: list[PhaseResult] = []
    sanitized_pytest_environment = sorted(
        name for name in _PYTEST_CONTROL_ENV if name in os.environ
    )
    junit_totals: JUnitTotals | None = None
    collection_totals: CollectionTotals | None = None

    try:
        with log_path.open("x", encoding="utf-8") as log, GateLock(lock_path):
            first_snapshot = _snapshot_tree(repo_root)
            worktree_errors = _blocking_worktree_errors(repo_root)
            if not args.preflight_only:
                committed_tree_error = _committed_tree_error(repo_root)
                if committed_tree_error:
                    worktree_errors.append(committed_tree_error)
            running_pytest = _running_pytest_processes()
            if running_pytest:
                worktree_errors.append(
                    "Another pytest process is already running; wait for it to finish: "
                    + " | ".join(running_pytest[:4])
                )
            checked_snapshot = _snapshot_tree(repo_root)
            if checked_snapshot != first_snapshot:
                tree_changed = True
                worktree_errors.append(
                    "HEAD, index, or worktree changed during gate admission checks."
                )
            if worktree_errors:
                error = " | ".join(worktree_errors)
                for worktree_error in worktree_errors:
                    message = f"PREFLIGHT FAIL: {worktree_error}\n"
                    _write_console(message)
                    log.write(message)
                wrapper_exit_code = 3 if tree_changed else 2
            else:
                source_snapshot_before = checked_snapshot
                with _materialized_gate_tree(
                    repo_root, source_snapshot_before
                ) as gate_root:
                    snapshot_before = _snapshot_tree(gate_root)
                    env = _subprocess_env(gate_root)
                    try:
                        for spec in _preflight_specs(gate_root):
                            phase_exit_code = _execute_phase(
                                spec,
                                cwd=gate_root,
                                log=log,
                                env=env,
                                results=phases,
                            )
                            if phase_exit_code != 0:
                                preflight_exit_code = phase_exit_code
                                _write_console(
                                    "PREFLIGHT FAIL: command exited "
                                    f"{phase_exit_code}; full gate not run.\n"
                                )
                                break
                        else:
                            preflight_exit_code = 0

                        wrapper_exit_code = preflight_exit_code
                        post_preflight_snapshot = _snapshot_tree(gate_root)
                        if post_preflight_snapshot != snapshot_before:
                            tree_changed = True
                            snapshot_after = post_preflight_snapshot
                            wrapper_exit_code = 3
                            _write_console(
                                "GATE INVALID: preflight changed the materialized "
                                "gate tree; full gate not run.\n"
                            )
                        elif preflight_exit_code == 0 and not args.preflight_only:
                            collection_dir.mkdir(parents=True, exist_ok=False)
                            full_command = _build_full_command(
                                repo_root=gate_root,
                                junit_path=junit_path,
                                workers=args.workers,
                                distribution=args.dist,
                            )
                            pytest_exit_code = _execute_phase(
                                PhaseSpec("pytest-full", full_command),
                                cwd=gate_root,
                                log=log,
                                env=_pytest_subprocess_env(
                                    gate_root, collection_dir
                                ),
                                results=phases,
                            )
                            wrapper_exit_code = pytest_exit_code
                            if junit_path.exists():
                                try:
                                    junit_totals = _parse_junit(
                                        junit_path,
                                        required_test_files=_tracked_test_census(
                                            gate_root
                                        ),
                                    )
                                except RuntimeError as exc:
                                    error = str(exc)
                                    if pytest_exit_code == 0:
                                        wrapper_exit_code = 5
                            elif pytest_exit_code == 0:
                                error = (
                                    "pytest exited 0 without creating its unique "
                                    "JUnit report"
                                )
                                wrapper_exit_code = 5
                            if (
                                pytest_exit_code == 0
                                and junit_totals is not None
                                and (
                                    junit_totals.failures > 0
                                    or junit_totals.errors > 0
                                )
                            ):
                                error = (
                                    "pytest exited 0 but JUnit reports failures or "
                                    "errors"
                                )
                                wrapper_exit_code = 5
                            if pytest_exit_code == 0 and junit_totals is not None:
                                try:
                                    collection_totals = (
                                        _validate_collection_manifests(
                                            collection_dir,
                                            collection_path,
                                            expected_workers=args.workers,
                                            required_test_files=(
                                                _tracked_test_census(gate_root)
                                            ),
                                            junit_totals=junit_totals,
                                        )
                                    )
                                except RuntimeError as exc:
                                    error = str(exc)
                                    wrapper_exit_code = 5
                    finally:
                        snapshot_after = _snapshot_tree(gate_root)
                        materialized_tree_changed = snapshot_after != snapshot_before
                        tree_changed = tree_changed or materialized_tree_changed
                        if materialized_tree_changed:
                            changed_paths = _git_bytes(
                                gate_root,
                                "status",
                                "--short",
                                "--untracked-files=all",
                            ).decode("utf-8", errors="replace").strip()
                            _write_console(
                                "GATE INVALID: materialized HEAD, index, or worktree "
                                "changed while validation ran: "
                                f"{changed_paths or '<status unavailable>'}\n"
                            )
                            wrapper_exit_code = 3

                source_snapshot_after = _snapshot_tree(repo_root)
                if source_snapshot_after != source_snapshot_before:
                    tree_changed = True
                    wrapper_exit_code = 3
                    _write_console(
                        "GATE INVALID: source HEAD, index, or worktree changed while "
                        "the materialized validation ran.\n"
                    )
    except RuntimeError as exc:
        if snapshot_before is not None:
            if phases and phases[-1].name == "pytest-full":
                pytest_exit_code = phases[-1].exit_code
            elif preflight_exit_code is None:
                preflight_exit_code = phases[-1].exit_code if phases else 5
            _write_console(f"GATE ERROR: {_exception_text(exc)}\n")
            wrapper_exit_code = 5
        else:
            _write_console(f"GATE REFUSED: {_exception_text(exc)}\n")
            wrapper_exit_code = 4
        error = _exception_text(exc)
    except KeyboardInterrupt:
        if phases:
            if phases[-1].name == "pytest-full":
                pytest_exit_code = phases[-1].exit_code
            elif preflight_exit_code is None:
                preflight_exit_code = phases[-1].exit_code
        interrupted = True
        wrapper_exit_code = 130
        error = "Interrupted"
        _write_console("GATE INTERRUPTED: validation did not complete.\n")
    except Exception as exc:
        if phases:
            if phases[-1].name == "pytest-full":
                pytest_exit_code = phases[-1].exit_code
            elif preflight_exit_code is None:
                preflight_exit_code = phases[-1].exit_code
        wrapper_exit_code = 5
        error = f"{type(exc).__name__}: {_exception_text(exc)}"
        _write_console(f"GATE ERROR: {error}\n")
    finally:
        if source_snapshot_before is not None:
            try:
                source_snapshot_after = _snapshot_tree(repo_root)
                source_tree_changed = source_snapshot_after != source_snapshot_before
                tree_changed = tree_changed or source_tree_changed
                if source_tree_changed and wrapper_exit_code == 0:
                    wrapper_exit_code = 3
            except Exception as exc:
                if not error:
                    error = f"Unable to capture final source tree snapshot: {exc}"
                if wrapper_exit_code == 0:
                    wrapper_exit_code = 5
        finished_at = _utc_now()
        elapsed_seconds = round(time.monotonic() - started, 3)
        log_text = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.exists()
            else ""
        )
        result = GateResult(
            label=label,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_seconds=elapsed_seconds,
            wrapper_exit_code=wrapper_exit_code,
            preflight_exit_code=preflight_exit_code,
            pytest_exit_code=pytest_exit_code,
            preflight_only=bool(args.preflight_only),
            interrupted=interrupted,
            error=error,
            tree_changed=tree_changed,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            command=full_command,
            phases=phases,
            sanitized_pytest_environment=sanitized_pytest_environment,
            summary=_extract_summary(log_text),
            log_path=str(log_path.relative_to(repo_root)),
            junit_path=(
                str(junit_path.relative_to(repo_root)) if junit_path.exists() else None
            ),
            junit_totals=junit_totals,
            collection_path=(
                str(collection_path.relative_to(repo_root))
                if collection_path.exists()
                else None
            ),
            collection_totals=collection_totals,
        )
        _write_manifest(manifest_path, result)
        if receipt_path is not None and wrapper_exit_code == 0:
            try:
                if source_snapshot_before is None:
                    raise RuntimeError("Successful gate has no admitted source snapshot")
                _write_success_receipt(
                    receipt_path,
                    repo_root=repo_root,
                    result=result,
                    source_snapshot=source_snapshot_before,
                    manifest_path=manifest_path,
                    junit_path=junit_path,
                    collection_path=collection_path,
                )
            except Exception as exc:
                receipt_path.unlink(missing_ok=True)
                wrapper_exit_code = 5
                receipt_error = f"Unable to write success receipt: {_exception_text(exc)}"
                error = f"{error} | {receipt_error}" if error else receipt_error
                result = replace(
                    result,
                    wrapper_exit_code=wrapper_exit_code,
                    error=error,
                )
                _write_manifest(manifest_path, result)
                _write_console(f"GATE ERROR: {receipt_error}\n")
        _write_console(
            f"Gate exit={wrapper_exit_code} preflight={preflight_exit_code} "
            f"pytest={pytest_exit_code} elapsed={elapsed_seconds:.1f}s "
            f"log={log_path.relative_to(repo_root)} "
            f"manifest={manifest_path.relative_to(repo_root)}\n"
        )
    return wrapper_exit_code


if __name__ == "__main__":
    raise SystemExit(main())