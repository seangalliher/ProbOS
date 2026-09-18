"""BF-758: one file-read floor, used by every path that can open a file.

A crew agent could read any file on the host in a single DM turn. `read_file`
is in `_MESH_READ_INTENT_POOLS`, `step_4h_mesh_read_parse` runs on every DM turn
with no config flag, and `FileReaderAgent._read_file` was a bare
`Path(path).read_text()`. `ReadFileTool` advertised "from the project tree" to
the model while `_resolve_path` passed an absolute path straight through. Two
independent readers, no bound on either, and one of them lying about it.

The allowlist that admits `read_file` to the conversational seam was reviewed
for "is this intent read-only". It is. **Read-only is not the same property as
bounded**, and nothing checked the second one.

Modelled on `url_guard`, and for the same reason: this separates *policy* from
*floor*. The floor is the credential vault and the governance databases, which
no configuration should be able to hand out. Policy is an optional operator
confinement, empty by default.

The first draft got that backwards -- it permitted only the workspace and the
project tree, which broke 24 integration tests. `read_file` on an arbitrary path
is a load-bearing core capability (it is the canonical intent in the mesh,
consensus, Hebbian and episodic suites), and confining it would also refuse
"read the file I just named" from the Captain. `url_guard` does not maintain a
list of permitted hosts; it refuses loopback whoever asked. Same shape here.

Longest-prefix-match decides overlaps, because two genuinely overlap: the agent
workspace root resolves *under* the runtime data directory, so a flat "deny the
data dir" would block the one folder agents are meant to work in.

`run_python` is deliberately NOT covered. `execution/isolation.py` states its
own boundary honestly -- "a determined script can still read host files by
absolute path" -- and raising that is Tier 2 (AD-995). This module closes the
ungoverned, unaudited, one-tag route, which is the part that was wrong.
"""

from __future__ import annotations

import logging
import ntpath
import os
import stat
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors ``ExecutionConfig.workspace_root``. A literal, not an import, so this
# guard works for a reader that has no runtime and no config at all.
_DEFAULT_WORKSPACE_ROOT = "data/execution/workspaces"

# Belt-and-braces on top of the floor: these are refused by NAME wherever they
# are, in case an operator relocates the vault outside the data directory.
# Taken from ``CredentialVaultConfig`` defaults -- the first draft guessed
# ``vault.json``/``credentials.json``, which are not files this system has ever
# written, so the check named nothing and only looked like a guard.
PROTECTED_LEAF_NAMES = frozenset({
    "credential_vault.json",
    "credential_keyring_index.json",
})


class FileAccessDenied(Exception):
    """A read was refused by the file-access floor."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(reason)


def _depth(root: Path) -> int:
    return len(root.parts)


def _longest_match(resolved: Path, roots: Iterable[Path]) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``."""
    best: Path | None = None
    for root in roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                if best is None or _depth(root) > _depth(best):
                    best = root
        except (OSError, ValueError):
            continue
    return best


def resolve_read_path(
    raw: str,
    *,
    protected_roots: Sequence[Path],
    exempt_roots: Sequence[Path] = (),
    permitted_roots: Sequence[Path] | None = None,
    relative_base: Path | None = None,
) -> Path:
    """The absolute path to read, or raise :class:`FileAccessDenied`.

    Three distinct ideas, kept separate because conflating them is what the
    first two drafts got wrong:

    * ``protected_roots`` -- the FLOOR. Refused whoever asked, however
      configured. The credential vault and the governance databases.
    * ``exempt_roots`` -- carve-outs INSIDE the floor that are legitimately
      agent-owned. The agent workspace resolves under the data directory, so
      without this a flat floor blocks the one folder agents work in. An
      exemption lifts the floor; it does not confine anything.
    * ``permitted_roots`` -- POLICY. ``None`` (default) means an operator has
      not confined reads. Confining is opt-in because ``read_file`` on an
      arbitrary path is a load-bearing core capability -- it is the canonical
      intent in the mesh, consensus, Hebbian and episodic suites, and the
      Captain names arbitrary paths.

    Resolution happens BEFORE containment, so a symlink pointing into the floor
    is caught -- the same ``resolve() + is_relative_to`` order
    ``WorkspaceManager.resolve_file`` uses.
    """
    if not raw or "\x00" in raw:
        raise FileAccessDenied(raw, "empty or malformed path")
    try:
        candidate = Path(raw)
        # A relative path must keep resolving the way its caller always did.
        # ``ReadFileTool._resolve_path`` rooted relative paths at the project
        # tree; resolving them against the process CWD instead silently broke
        # every relative read the Builder makes.
        if relative_base is not None and not candidate.is_absolute():
            candidate = relative_base / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileAccessDenied(raw, f"path could not be resolved: {exc}") from exc

    if resolved.name in PROTECTED_LEAF_NAMES:
        raise FileAccessDenied(raw, "that file holds credentials and is not readable")

    protect = _longest_match(resolved, protected_roots)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots)
        # Longest prefix wins: a deeper exemption lifts a shallower floor.
        if exempt is None or _depth(exempt) <= _depth(protect):
            raise FileAccessDenied(
                raw, "path is inside the runtime's protected data directory"
            )

    if permitted_roots and _longest_match(resolved, permitted_roots) is None:
        raise FileAccessDenied(raw, "path is outside every readable root")
    return resolved


def permitted_read_roots(runtime: Any) -> list[Path]:
    """Operator POLICY: confine reads to these roots, or ``[]`` for no limit.

    Empty by default. ``read_file`` is a core capability used across the mesh,
    and the Captain legitimately asks agents to read files anywhere -- so
    confinement is opt-in. The agent workspace is always added when a limit IS
    set, because an agent must be able to read its own working folder.
    """
    infra = getattr(getattr(runtime, "config", None), "security_infra", None)
    configured = getattr(infra, "read_roots", None) or []
    if not configured:
        return []
    roots: list[Path] = []
    for entry in configured:
        try:
            roots.append(Path(str(entry)).resolve())
        except (OSError, ValueError):
            logger.warning(
                "BF-758: configured read_roots entry %r is not a usable path; "
                "ignoring it", entry,
            )
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        roots.append(_resolve_workspace_root(workspace))
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
    return roots


def protected_read_roots(runtime: Any) -> list[Path]:
    """The floor: the runtime data directory (vault, governance databases).

    Falls back to the platform data dir for the same reason as above -- the
    readers that need this most have no runtime.
    """
    data_dir = getattr(runtime, "data_dir", None)
    if data_dir is None:
        try:
            from probos.execution.workspace import _platform_data_dir

            return [_platform_data_dir().resolve()]
        except Exception:
            return []
    try:
        return [Path(data_dir).resolve()]
    except (OSError, ValueError):
        return []


def workspace_exempt_roots(runtime: Any) -> list[Path]:
    """The agent workspace tree, which lives under the data dir but is theirs."""
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        return [_resolve_workspace_root(workspace)]
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
        return []


def resolve_for_runtime(
    raw: str, runtime: Any, *, relative_base: Path | None = None
) -> Path:
    """Convenience wrapper: resolve *raw* against *runtime*'s floor and policy."""
    return resolve_read_path(
        raw,
        protected_roots=protected_read_roots(runtime),
        exempt_roots=workspace_exempt_roots(runtime),
        permitted_roots=permitted_read_roots(runtime) or None,
        relative_base=relative_base,
    )


INSTRUCTION_FILE_BYTES = 8192


class BoundedReadStatus(str, Enum):
    OK = "ok"
    ABSENT = "absent"
    EMPTY = "empty"
    TRUNCATED = "truncated"
    INVALID_PATH = "invalid_path"
    DENIED = "denied"
    NOT_REGULAR = "not_regular"
    UNSAFE_PATH = "unsafe_path"
    CHANGED = "changed"
    IO_ERROR = "io_error"
    INVALID_UTF8 = "invalid_utf8"
    BINARY = "binary"


@dataclass(frozen=True)
class BoundedTextRead:
    """An instruction read; only ABSENT permits same-directory fallback."""

    status: BoundedReadStatus
    text: str = field(default="", repr=False)
    bytes_read: int = 0

    def __post_init__(self) -> None:
        if type(self.status) is not BoundedReadStatus or type(self.text) is not str:
            raise TypeError("bounded reads require a typed status and text")
        if type(self.bytes_read) is not int or not 0 <= self.bytes_read <= INSTRUCTION_FILE_BYTES + 1:
            raise ValueError("bounded read byte count exceeds its limit")
        if len(self.text.encode("utf-8")) > INSTRUCTION_FILE_BYTES:
            raise ValueError("bounded read text exceeds its limit")
        if any((ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) <= 159 for char in self.text):
            raise ValueError("bounded read text contains binary controls")
        if self.text and self.status not in (
            BoundedReadStatus.OK, BoundedReadStatus.EMPTY, BoundedReadStatus.TRUNCATED,
        ):
            raise ValueError("unavailable reads must withhold content")


class _UnsafeInstructionPath(Exception):
    pass


class _ChangedInstructionPath(Exception):
    pass


class _NotRegularInstructionPath(Exception):
    pass


def validate_read_location(raw: str | Path, *, relative_base: Path | None = None) -> Path:
    """Validate a discovery location lexically, without cwd or filesystem I/O.

    This is not authorization. Bounded reads still validate policy and handles.
    """
    if isinstance(raw, Path):
        raw = str(raw)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("invalid path")
    raw.encode("utf-8", errors="strict")
    spelling = raw.replace("/", "\\")
    drive, tail = ntpath.splitdrive(spelling)
    if (
        spelling.startswith(("\\\\?\\", "\\\\.\\"))
        or (drive and not tail.startswith("\\"))
        or ":" in tail
        or any(ord(char) < 32 for char in raw)
        or PureWindowsPath(raw).is_reserved()
    ):
        raise ValueError("invalid path")
    candidate = Path(raw)
    if os.name == "nt" and candidate.root and not candidate.drive:
        raise ValueError("device or drive-relative path")
    if not candidate.is_absolute():
        if not isinstance(relative_base, Path) or not relative_base.is_absolute():
            raise ValueError("absolute read authority required")
        candidate = validate_read_location(relative_base) / candidate
    return Path(os.path.abspath(candidate))


def _instruction_path(raw: str, root: Path) -> Path:
    root = validate_read_location(root)
    candidate = validate_read_location(raw, relative_base=root)
    if not candidate.is_relative_to(root):
        raise FileAccessDenied(raw, "path is outside the pinned root")
    return candidate


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def _same_identity(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode)) == (
        after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode),
    )


def _same_file(
    before: os.stat_result, after: os.stat_result, *, opened: bool = False,
) -> bool:
    same_revision = (before.st_size, before.st_mtime_ns) == (
        after.st_size, after.st_mtime_ns,
    )
    # Windows lstat and CRT fstat can expose different ctime meanings. Compare
    # ctime only within the same API, including a pre/post-read handle snapshot.
    same_ctime = opened and os.name == "nt" or before.st_ctime_ns == after.st_ctime_ns
    return _same_identity(before, after) and same_revision and same_ctime


@lru_cache(maxsize=1)
def _windows_file_api() -> Any:
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    )
    api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    api.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    )
    api.GetFileInformationByHandleEx.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    return api


def _windows_handle_path(handle: int) -> Path:
    import ctypes

    api = _windows_file_api()
    needed = api.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not needed:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(needed + 1)
    length = api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise _UnsafeInstructionPath
    name = buffer.value
    if name.startswith("\\\\?\\UNC\\"):
        name = "\\\\" + name[8:]
    elif name.startswith("\\\\?\\"):
        name = name[4:]
    return Path(name)


def _open_windows_instruction_path(path: Path, *, directory: bool) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    api = _windows_file_api()
    handle = api.CreateFileW(
        str(path), 0x80 if directory else 0x80000000,
        0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = AttributeTagInfo()
        if not api.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400 or _windows_handle_path(handle) != path:
            raise _UnsafeInstructionPath
        # No FILE_SHARE_DELETE: every ancestor and the file stay pinned until
        # the read and post-read validation finish. No directory bytes are read.
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        api.CloseHandle(handle)
        raise
    return fd


def _validate_instruction_chain(
    paths: list[Path], snapshots: list[os.stat_result], descriptors: list[int],
) -> None:
    for index, (path, before, fd) in enumerate(zip(paths, snapshots, descriptors)):
        named = path.lstat()
        opened = os.fstat(fd)
        if _is_reparse(named):
            raise _UnsafeInstructionPath
        same = (
            _same_file(before, named) and _same_file(before, opened, opened=True)
            if index == len(paths) - 1
            else _same_identity(before, named) and _same_identity(before, opened)
        )
        if not same:
            raise _ChangedInstructionPath
        if os.name == "nt":
            import msvcrt

            if _windows_handle_path(msvcrt.get_osfhandle(fd)) != path:
                raise _UnsafeInstructionPath


def _decode_instruction_bytes(data: bytes, *, truncated: bool) -> BoundedTextRead:
    payload = data[:INSTRUCTION_FILE_BYTES]
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        # Only the terminal partial code point of a bounded prefix is withheld.
        # Any invalid interior byte invalidates the selected file, not fallback.
        if truncated and exc.reason == "unexpected end of data" and exc.end == len(exc.object):
            try:
                text = exc.object[:exc.start].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                return BoundedTextRead(BoundedReadStatus.INVALID_UTF8, bytes_read=len(data))
        else:
            return BoundedTextRead(BoundedReadStatus.INVALID_UTF8, bytes_read=len(data))
    if any((ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) <= 159 for char in text):
        return BoundedTextRead(BoundedReadStatus.BINARY, bytes_read=len(data))
    status = (
        BoundedReadStatus.TRUNCATED if truncated else
        BoundedReadStatus.OK if text.strip() else BoundedReadStatus.EMPTY
    )
    return BoundedTextRead(status, text=text, bytes_read=len(data))


def read_bounded_utf8(
    raw: str,
    *,
    authorized_root: Path,
    protected_roots: Sequence[Path],
    exempt_roots: Sequence[Path] = (),
    permitted_roots: Sequence[Path] | None = None,
) -> BoundedTextRead:
    """Authorize, pin and validate a regular-file handle before any byte read.

    At most 8,192 bytes plus one detection byte are read. The caller supplies
    authority explicitly; this API never selects cwd or creates exemptions.
    An observed name/identity/size/time change withholds the snapshot. This is
    not an atomic-snapshot promise against arbitrary in-place writers.
    """
    descriptors: list[int] = []
    selected = False
    bytes_read = 0
    try:
        candidate = _instruction_path(raw, authorized_root)
        paths = [*reversed(candidate.parents), candidate]
        snapshots: list[os.stat_result] = []
        for index, path in enumerate(paths):
            info = path.lstat()
            if _is_reparse(info):
                raise _UnsafeInstructionPath
            is_file = index == len(paths) - 1
            if not (stat.S_ISREG(info.st_mode) if is_file else stat.S_ISDIR(info.st_mode)):
                raise _NotRegularInstructionPath
            snapshots.append(info)
        selected = True
        resolved = resolve_read_path(
            str(candidate), protected_roots=protected_roots,
            exempt_roots=exempt_roots, permitted_roots=permitted_roots,
        )
        if resolved != candidate or not resolved.is_relative_to(authorized_root):
            raise _UnsafeInstructionPath
        for index, path in enumerate(paths):
            directory = index != len(paths) - 1
            if os.name == "nt":
                fd = _open_windows_instruction_path(path, directory=directory)
            else:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                flags |= os.O_DIRECTORY if directory else os.O_NONBLOCK
                fd = os.open(
                    str(path) if index == 0 else path.name, flags,
                    **({"dir_fd": descriptors[-1]} if descriptors else {}),
                )
            descriptors.append(fd)
        _validate_instruction_chain(paths, snapshots, descriptors)
        opened_snapshot = os.fstat(descriptors[-1])
        data = os.read(descriptors[-1], INSTRUCTION_FILE_BYTES + 1)
        bytes_read = len(data)
        _validate_instruction_chain(paths, snapshots, descriptors)
        if not _same_file(opened_snapshot, os.fstat(descriptors[-1])):
            raise _ChangedInstructionPath
        if len(data) < min(snapshots[-1].st_size, INSTRUCTION_FILE_BYTES + 1):
            result = BoundedTextRead(BoundedReadStatus.IO_ERROR, bytes_read=bytes_read)
        else:
            result = _decode_instruction_bytes(data, truncated=len(data) > INSTRUCTION_FILE_BYTES)
    except FileNotFoundError:
        result = BoundedTextRead(
            BoundedReadStatus.CHANGED if selected else BoundedReadStatus.ABSENT,
            bytes_read=bytes_read,
        )
    except FileAccessDenied:
        result = BoundedTextRead(BoundedReadStatus.DENIED)
    except _UnsafeInstructionPath:
        result = BoundedTextRead(BoundedReadStatus.UNSAFE_PATH, bytes_read=bytes_read)
    except _ChangedInstructionPath:
        result = BoundedTextRead(BoundedReadStatus.CHANGED, bytes_read=bytes_read)
    except _NotRegularInstructionPath:
        result = BoundedTextRead(BoundedReadStatus.NOT_REGULAR)
    except (ValueError, UnicodeError, RuntimeError):
        result = BoundedTextRead(BoundedReadStatus.INVALID_PATH)
    except OSError:
        result = BoundedTextRead(BoundedReadStatus.IO_ERROR, bytes_read=bytes_read)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
    if result.status not in (BoundedReadStatus.OK, BoundedReadStatus.EMPTY, BoundedReadStatus.ABSENT):
        logger.warning(
            "AD-1200: bounded repository-instruction read failed or is partial "
            "(%s); applicable rules may be unknown; returning a typed notice "
            "and only a validated prefix, never fallback content",
            result.status.value,
        )
    return result
