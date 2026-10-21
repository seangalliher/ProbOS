"""AD-544: Native SWE tool suite — 12 ``Tool``-Protocol adapters wrapping
existing ProbOS capabilities (FileReaderAgent, FileWriterAgent, ShellCommandAgent,
FileSearchAgent, CodebaseIndex, standing-orders manuals, system self-model).

Each adapter satisfies AD-423a ``Tool`` Protocol. ``register_native_swe_tools``
batch-registers all twelve into the AD-423a/b ``ToolRegistry`` under the
``engineering`` domain with rank-keyed ``default_permissions`` aligned to
AD-423b's permission ladder.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import logging
import os
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from probos.cognitive.standing_orders import (
    is_standing_order_name,
    standing_order_names,
    standing_orders_dir,
)
from probos.execution.command_env import build_command_env
from probos.execution.command_escalation import CommandEscalations
from probos.execution.command_gate import (
    COMMAND_POLICY_UNAVAILABLE,
    CommandGateVerdict,
    CommandPolicyGate,
    policy_result_metadata,
)
from probos.execution.process_tree import ProcessTree, process_tree_popen_kwargs
from probos.execution.workspace_results import (
    RecoverRead,
    SourceRef,
    WorkspaceReadContext,
    WorkspaceResultError,
    WorkspaceSlice,
    drained_result_io,
    is_workspace_result_path,
    resolve_workspace_results,
)
from probos.repository_instructions import (
    InstructionObservation,
    discover_repository_instructions,
    instruction_read_policy,
    repository_instruction_directory,
)
from probos.security.file_access import (
    FileAccessDenied,
    permitted_read_roots,
    protected_read_roots,
    read_verified_file,
    resolve_for_runtime,
    workspace_exempt_roots,
)
from probos.tools.protocol import (
    Tool,
    ToolResult,
    ToolType,
    refuse_undeclared_params,
)

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_READ_ATTRIBUTES = 0x80
_DELETE = 0x00010000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_OPEN_ALWAYS = 4
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _strict_native_target_supported() -> bool:
    return os.name == "nt"


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("file_attributes", ctypes.c_uint32),
        ("creation_time", _FileTime),
        ("last_access_time", _FileTime),
        ("last_write_time", _FileTime),
        ("volume_serial_number", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


@contextmanager
def _locked_native_target(
    path: Path,
    expected: Path,
    root: Path,
    *,
    create: bool = True,
) -> Any:
    if os.name != "nt":
        raise OSError("strict native file locking is unsupported on this platform")
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = (ctypes.c_wchar_p,)
    get_attributes.restype = ctypes.c_uint32
    get_file_information = kernel32.GetFileInformationByHandle
    get_file_information.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    get_file_information.restype = ctypes.c_int
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    )
    get_final_path.restype = ctypes.c_uint32

    handles: list[int] = []
    target_file: Any | None = None
    try:
        relative_parent = expected.parent.relative_to(root)
        chain = [root]
        current = root
        for part in relative_parent.parts:
            current /= part
            chain.append(current)
        for directory in chain:
            attributes = get_attributes(str(directory))
            if attributes == 0xFFFFFFFF:
                raise OSError(ctypes.get_last_error(), "directory attributes unavailable")
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("strict native path crosses a reparse point")
            handle = create_file(
                str(directory),
                _FILE_READ_ATTRIBUTES | _DELETE,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            if handle == _INVALID_HANDLE_VALUE:
                raise OSError(ctypes.get_last_error(), "directory lock unavailable")
            handles.append(int(handle))
        if path.exists():
            attributes = get_attributes(str(path))
            if attributes == 0xFFFFFFFF:
                raise OSError(ctypes.get_last_error(), "target attributes unavailable")
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("strict native target is a reparse point")
        if path.resolve(strict=False) != expected:
            raise OSError("strict native target changed after authorization")
        target_handle = create_file(
            str(expected),
            _GENERIC_READ | _GENERIC_WRITE | _FILE_READ_ATTRIBUTES,
            _FILE_SHARE_READ,
            None,
            _OPEN_ALWAYS if create else _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if target_handle == _INVALID_HANDLE_VALUE:
            error = ctypes.get_last_error()
            if not create and error in {2, 3}:
                raise FileNotFoundError(error, "target file not found", str(expected))
            raise OSError(error, "target handle unavailable")
        information = _ByHandleFileInformation()
        if not get_file_information(target_handle, ctypes.byref(information)):
            close_handle(target_handle)
            raise OSError(ctypes.get_last_error(), "target identity unavailable")
        if information.file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            close_handle(target_handle)
            raise OSError("strict native target is a reparse point")
        if information.number_of_links != 1:
            close_handle(target_handle)
            raise OSError("strict native target has multiple filesystem links")
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_final_path(target_handle, buffer, len(buffer), 0)
        if length == 0 or length >= len(buffer):
            close_handle(target_handle)
            raise OSError(ctypes.get_last_error(), "target final path unavailable")
        final_path = buffer.value
        if final_path.startswith("\\\\?\\"):
            final_path = final_path[4:]
        if Path(final_path).resolve(strict=False) != expected:
            close_handle(target_handle)
            raise OSError("opened target does not match authorized target")
        fd = msvcrt.open_osfhandle(
            int(target_handle), os.O_RDWR | os.O_BINARY
        )
        target_file = os.fdopen(fd, "r+b")
        yield target_file
    finally:
        if target_file is not None:
            target_file.close()
        for handle in reversed(handles):
            close_handle(handle)


def _resolve_path(path: str) -> Path:
    """Resolve a user-supplied path against project root if relative."""
    p = Path(path)
    return p if p.is_absolute() else (_PROJECT_ROOT / p)


@dataclass(frozen=True)
class InstructionToolResult(ToolResult):
    repository_instructions: InstructionObservation = field(kw_only=True, repr=False)

    def __post_init__(self) -> None:
        if type(self.repository_instructions) is not InstructionObservation:
            raise TypeError("file guidance requires a typed instruction observation")


@dataclass(frozen=True)
class SourceToolResult(ToolResult):
    """A verified original-file read, carrying the reference a recovery re-reads."""

    source_reference: SourceRef = field(kw_only=True, repr=False)
    recovery: bool = field(default=False, kw_only=True)


@dataclass(frozen=True)
class InstructionSourceToolResult(InstructionToolResult):
    """``SourceToolResult`` for a read that also carries repository instructions."""

    source_reference: SourceRef = field(kw_only=True, repr=False)
    recovery: bool = field(default=False, kw_only=True)


@dataclass(frozen=True)
class WorkspaceSliceToolResult(ToolResult):
    """An exact slice of an offloaded result, read back through the typed owner."""

    workspace_slice: WorkspaceSlice = field(kw_only=True, repr=False)


@dataclass(frozen=True)
class RecoveryFailureToolResult(ToolResult):
    """A typed, content-free refusal of a promised recovery or private read."""

    delivery_error: str = field(kw_only=True)


def _read_context(context: dict[str, Any] | None) -> WorkspaceReadContext | None:
    candidate = (context or {}).get("_workspace_read")
    if candidate is None:
        return None
    if type(candidate) is not WorkspaceReadContext or (
        candidate.binding.agent_id != (context or {}).get("agent_id")
        or candidate.binding.agent_id != candidate.scope.agent_id
    ):
        raise WorkspaceResultError("reference_unavailable")
    if type(candidate.directive) is RecoverRead:
        reference = candidate.directive.reference
        if type(reference) is not SourceRef:
            raise WorkspaceResultError("reference_unavailable")
        candidate.scope.validate(reference.path, candidate.directive)
    return candidate


def _workspace_result_path(
    runtime: object, raw: str, target: Path, context: dict[str, Any] | None,
) -> bool:
    candidates = (_resolve_path(raw), target)
    if not any(is_workspace_result_path(path) for path in candidates):
        return False
    from probos.execution.workspace import WorkspaceManager

    roots = workspace_exempt_roots(runtime)
    configured = getattr(getattr(getattr(runtime, "config", None), "execution", None), "workspace_root", None)
    if isinstance(configured, (str, Path)):
        # Retain the lexical configured root as well as its resolved spelling:
        # a private path redirected out through a link must still fail closed.
        roots.append(WorkspaceManager(configured).root)
    read = _read_context(context)
    if read is not None:
        roots.append(read.binding.root)
    return any(
        is_workspace_result_path(path) and path.is_relative_to(root)
        for path in candidates for root in roots
    )


def _verified_source_result(
    target: Path, runtime: object, read: WorkspaceReadContext,
    start: int | None, end: int | None,
) -> ToolResult:
    read.scope.validate(str(target), read.directive)
    expected = read.directive.reference if type(read.directive) is RecoverRead else None
    try:
        snapshot = read_verified_file(
            target, protected_roots=protected_read_roots(runtime),
            exempt_roots=workspace_exempt_roots(runtime),
            permitted_roots=permitted_read_roots(runtime) or None,
        )
    except (FileNotFoundError, FileAccessDenied, OSError) as exc:
        if expected is not None:
            raise WorkspaceResultError("source_changed") from exc
        # A fresh read keeps the native producer-error path: the caller's own
        # handlers turn this into the ordinary error result. There is no
        # fallback re-read, because a second, unverified read could observe
        # something the verified read did not.
        raise
    digest = hashlib.sha256(snapshot.data).hexdigest()
    if expected is not None and (
        Path(expected.path) != target or expected.identity != snapshot.identity
        or expected.revision != snapshot.revision or expected.raw_sha256 != digest
    ):
        raise WorkspaceResultError("source_changed")
    # Match Path.read_text's UTF-8 and universal-newline behavior, including
    # the whole-file trailing newline; ordinary sliced reads use splitlines.
    with io.TextIOWrapper(io.BytesIO(snapshot.data), encoding="utf-8", newline=None) as stream:
        text = stream.read()
    lines = text.splitlines()
    whole = start is None and end is None
    selected = slice(start or 0, end if end is not None else len(lines))
    first, last, _ = selected.indices(len(lines))
    if not whole:
        text = "\n".join(lines[selected])
    reference = SourceRef(
        read.binding.agent_id, read.scope.run_nonce, str(target),
        snapshot.identity, snapshot.revision, digest, first, max(first, last), len(lines), whole,
    )
    result = _file_read_result(text, target, runtime)
    if isinstance(result, InstructionToolResult):
        return InstructionSourceToolResult(
            output=text, repository_instructions=result.repository_instructions,
            source_reference=reference, recovery=expected is not None,
        )
    return SourceToolResult(output=text, source_reference=reference, recovery=expected is not None)


async def _workspace_slice_result(
    runtime: object, target: Path, context: dict[str, Any] | None,
    offset: int | None, limit: int | None,
) -> ToolResult:
    read = _read_context(context)
    if read is None:
        owner = resolve_workspace_results(runtime)
        agent_id = (context or {}).get("agent_id")
        registry = getattr(runtime, "registry", None)
        registered = registry.get(agent_id) if registry is not None and type(agent_id) is str else None
        binding = owner.bind_agent(agent_id, registered)
    else:
        owner, binding = read.owner, read.binding
    selected = await owner.read_tool_result_slice(binding, str(target), offset, limit)
    return WorkspaceSliceToolResult(output=selected.text, workspace_slice=selected)


def _file_read_result(text: str, target: Path, runtime: object) -> ToolResult:
    observation = discover_repository_instructions(
        target.parent,
        global_directory=repository_instruction_directory(getattr(runtime, "data_dir", None)),
        policy=instruction_read_policy(runtime),
    )
    if not observation.targets and not observation.notices:
        return ToolResult(output=text)
    return InstructionToolResult(output=text, repository_instructions=observation)


# --------------------------------------------------------------------------
# Read-only tools (Trust 0.0+ Ensign / READ permission)
# --------------------------------------------------------------------------


class ReadFileTool:
    """AD-544: Read a file via FileReaderAgent."""

    tool_id: str = "read_file"
    name: str = "Read File"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    # BF-758: the boundary is the runtime data directory -- the credential
    # vault and the governance databases -- which is refused unconditionally.
    # This previously claimed "from the project tree" while passing absolute
    # paths through; a first BF-758 draft replaced that with a claim about
    # workspace confinement that is only true when an operator sets
    # ``security_infra.read_roots``. Both were false by default. This says what
    # is actually enforced with no configuration.
    description: str = (
        "Read a file's contents. Relative paths resolve against the project "
        "tree. The runtime's own data directory is not readable."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": ["path"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    def resolve_source_path(self, path: str) -> Path:
        """The file ``read_file`` would read for ``path`` under the runtime's read policy."""
        return resolve_for_runtime(path, self._runtime, relative_base=_PROJECT_ROOT)

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        path = params.get("path")
        if not path:
            return ToolResult(error="path is required")
        try:
            read = _read_context(context)
            try:
                target = self.resolve_source_path(str(path))
            except Exception as exc:
                if read is not None and type(read.directive) is RecoverRead:
                    raise WorkspaceResultError("source_changed") from exc
                return ToolResult(error=f"read_file refused: {exc}")
            if read is not None:
                read.scope.validate(str(target), read.directive)
            offset = params.get("offset")
            limit = params.get("limit")
            private_candidate = is_workspace_result_path(target) or is_workspace_result_path(Path(str(path)))
            if private_candidate and await drained_result_io(
                lambda: _workspace_result_path(self._runtime, str(path), target, context),
            ):
                return await _workspace_slice_result(self._runtime, target, context, offset, limit)
            if read is not None:
                start = int(offset or 0) if offset is not None or limit is not None else None
                end = (start or 0) + int(limit) if limit is not None else None
                return await drained_result_io(
                    lambda: _verified_source_result(target, self._runtime, read, start, end),
                )
            text = target.read_text(encoding="utf-8")
            if offset is not None or limit is not None:
                lines = text.splitlines()
                start = int(offset or 0)
                end = start + int(limit) if limit is not None else len(lines)
                text = "\n".join(lines[start:end])
            return _file_read_result(text, target, self._runtime)
        except WorkspaceResultError as exc:
            return RecoveryFailureToolResult(error=exc.code, delivery_error=exc.code)
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except Exception as exc:
            if type((context or {}).get("_workspace_read")) is WorkspaceReadContext:
                logger.warning(
                    "Verified native file read failed; no source reference is "
                    "available and the original error result is returned",
                )
            else:
                logger.warning(
                    "AD-544 ReadFileTool failed for path=%s: %s; returning error ToolResult",
                    path,
                    exc,
                )
            return ToolResult(error=f"read_file failed: {exc}")


class ListFilesTool:
    """AD-544: Glob-search files via FileSearchAgent semantics."""

    tool_id: str = "list_files"
    name: str = "List Files"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "List files in a directory matching a glob pattern."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"files": {"type": "array", "items": {"type": "string"}}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(error="pattern is required")
        path = params.get("path") or "."
        try:
            base = _resolve_path(str(path))
            matches = [str(p.relative_to(_PROJECT_ROOT)) for p in base.glob(pattern)]
            return ToolResult(output={"files": matches})
        except Exception as exc:
            logger.warning(
                (
                    "Strict list-files operation failed reason_code=consumer_failed "
                    "error_type=%s; returning a bounded error"
                    if (context or {}).get("_effect_dispatch_context") is not None
                    else "AD-544 ListFilesTool failed for pattern=%s path=%s: %s"
                ),
                *(
                    (type(exc).__name__,)
                    if (context or {}).get("_effect_dispatch_context") is not None
                    else (pattern, path, exc)
                ),
            )
            return ToolResult(
                error=(
                    "list_files_failed"
                    if (context or {}).get("_effect_dispatch_context") is not None
                    else f"list_files failed: {exc}"
                )
            )


class CodebaseQueryTool:
    """AD-544: Semantic-keyword query against CodebaseIndex."""

    tool_id: str = "codebase_query"
    name: str = "Codebase Query"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = "Query the codebase for files matching a concept."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"concept": {"type": "string"}},
        "required": ["concept"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"matches": {"type": "array"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        concept = params.get("concept")
        if not concept:
            return ToolResult(error="concept is required")
        index = getattr(self._runtime, "codebase_index", None)
        if index is None:
            return ToolResult(error="codebase_index unavailable on runtime")
        try:
            return ToolResult(output=index.query(str(concept)))
        except Exception as exc:
            logger.warning("AD-544 CodebaseQueryTool failed: %s", exc)
            return ToolResult(error=f"codebase_query failed: {exc}")


class CodebaseFindCallersTool:
    """AD-544: Find callers of a method via CodebaseIndex."""

    tool_id: str = "codebase_find_callers"
    name: str = "Codebase Find Callers"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = "Find call sites of a given method name in the codebase."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "method_name": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["method_name"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"callers": {"type": "array"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        name = params.get("method_name")
        if not name:
            return ToolResult(error="method_name is required")
        index = getattr(self._runtime, "codebase_index", None)
        if index is None:
            return ToolResult(error="codebase_index unavailable on runtime")
        try:
            return ToolResult(
                output=index.find_callers(
                    str(name), max_results=int(params.get("max_results", 10))
                )
            )
        except Exception as exc:
            return ToolResult(error=f"codebase_find_callers failed: {exc}")


class CodebaseFindTestsTool:
    """AD-544: Find tests covering a source file."""

    tool_id: str = "codebase_find_tests"
    name: str = "Codebase Find Tests"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = "Find test files that cover a given source file."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"tests": {"type": "array"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        path = params.get("file_path")
        if not path:
            return ToolResult(error="file_path is required")
        index = getattr(self._runtime, "codebase_index", None)
        if index is None:
            return ToolResult(error="codebase_index unavailable on runtime")
        try:
            return ToolResult(output=index.find_tests_for(str(path)))
        except Exception as exc:
            return ToolResult(error=f"codebase_find_tests failed: {exc}")


class CodebaseGetImportsTool:
    """AD-544: List imports of a file."""

    tool_id: str = "codebase_get_imports"
    name: str = "Codebase Get Imports"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = "List the imports of a Python file."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"imports": {"type": "array"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        path = params.get("file_path")
        if not path:
            return ToolResult(error="file_path is required")
        index = getattr(self._runtime, "codebase_index", None)
        if index is None:
            return ToolResult(error="codebase_index unavailable on runtime")
        try:
            return ToolResult(output=index.get_imports(str(path)))
        except Exception as exc:
            return ToolResult(error=f"codebase_get_imports failed: {exc}")


class CodebaseReadSourceTool:
    """AD-544: Read a file with optional line slicing."""

    tool_id: str = "codebase_read_source"
    name: str = "Codebase Read Source"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = "Read a source file with optional start_line/end_line slicing."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["file_path"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    def resolve_source_path(self, path: str) -> Path:
        """The file ``codebase_read_source`` would read for ``path`` under the read policy."""
        return resolve_for_runtime(path, self._runtime, relative_base=_PROJECT_ROOT)

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        path = params.get("file_path")
        if not path:
            return ToolResult(error="file_path is required")
        try:
            read = _read_context(context)
            try:
                target = self.resolve_source_path(str(path))
            except Exception as exc:
                if read is not None and type(read.directive) is RecoverRead:
                    raise WorkspaceResultError("source_changed") from exc
                raise
            if read is not None:
                read.scope.validate(str(target), read.directive)
            private_candidate = is_workspace_result_path(target) or is_workspace_result_path(Path(str(path)))
            if private_candidate and await drained_result_io(
                lambda: _workspace_result_path(self._runtime, str(path), target, context),
            ):
                raise WorkspaceResultError("workspace_reader_required")
            start = params.get("start_line")
            end = params.get("end_line")
            if read is not None:
                first = max(0, int(start or 1) - 1) if start is not None or end is not None else None
                last = int(end) if end is not None else None
                return await drained_result_io(
                    lambda: _verified_source_result(target, self._runtime, read, first, last),
                )
            text = target.read_text(encoding="utf-8")
            if start is not None or end is not None:
                lines = text.splitlines()
                s = max(0, int(start or 1) - 1)
                e = int(end) if end is not None else len(lines)
                text = "\n".join(lines[s:e])
            return _file_read_result(text, target, self._runtime)
        except WorkspaceResultError as exc:
            return RecoveryFailureToolResult(error=exc.code, delivery_error=exc.code)
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except Exception as exc:
            return ToolResult(error=f"codebase_read_source failed: {exc}")


# AD-1179: the standing-orders scope vocabulary, declared ONCE.
#
# It was written out four times -- the schema enum, the description prose, the
# ``invoke()`` gate, and the refusal string -- which is the BF-701 shape one tool
# over: a vocabulary restated beside its own executable gate, where the two can
# silently disagree and the agent is the one who finds out.
#
# Ordered tuple, never a set: Python string hashing is randomised per process,
# so a set-derived enum would reorder the wire bytes an LLM receives on every
# boot.
_STANDING_ORDERS_SCOPES: tuple[str, ...] = ("ship", "department", "agent")

# BF-910: fixed texts, so no refusal or failure echoes the caller's value or a path.
_STANDING_ORDERS_NAME_REFUSAL = (
    "department must name one standing-orders file: 1 to 64 ASCII letters, "
    "digits, '_' or '-', for example 'engineering'"
)
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)


def _exception_kind(exc: BaseException) -> str:
    """BF-910 (D24): the class name of *exc*, read without running code of its class or metaclass.

    The tool's ``try`` holds the caller's ``department`` lookup, so its handler can
    receive an exception of a caller's class. For a class whose metaclass is
    exactly ``type``, ``type``'s own ``__name__`` descriptor answers, and only an
    exact ``str`` is used; any other class or name is reported as ``Exception``.
    """
    cls = type(exc)
    if type(cls) is not type:
        return "Exception"
    name = cls.__name__
    return name if type(name) is str else "Exception"


class StandingOrdersLookupTool:
    """AD-544: Read a standing-orders manual file.

    BF-910: ``department`` selects one name from the flat directory the loader
    composes agents' standing orders from (``standing_orders_dir()``); it is
    never joined into a path unchecked, and the read is a verified read under
    the BF-758 floor and the operator's read policy.
    """

    tool_id: str = "standing_orders_lookup"
    name: str = "Standing Orders Lookup"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = (
        "Read the standing-orders manual for "
        + "/".join(_STANDING_ORDERS_SCOPES)
        + " scope."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": list(_STANDING_ORDERS_SCOPES)},
            "department": {"type": "string"},
        },
        "required": ["scope"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
    }

    def __init__(self, runtime: "ProbOSRuntime", orders_dir: Path | None = None) -> None:
        self._runtime = runtime
        # BF-910: None reads the loader's directory at each call; tests inject one.
        self._orders_dir = orders_dir

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        scope = params.get("scope")
        # BF-910 (D21): the type first, so a caller's __eq__ or __ne__ does not run.
        if type(scope) is not str or scope not in _STANDING_ORDERS_SCOPES:
            return ToolResult(
                error="scope must be one of " + "|".join(_STANDING_ORDERS_SCOPES)
            )
        # BF-910 (D23): the department lookup is inside the try, so a mapping whose
        # get raises is answered with the handler's fixed text, not raised out of invoke.
        try:
            name: object = "ship"
            if scope != "ship":
                # The department and agent tiers are both <name>.md in the one flat
                # directory (compose_instructions), so both scopes select by name.
                name = params.get("department")
                # BF-910 (D20): the type first, so a subclass or a non-string is not compared.
                if name is None or (type(name) is str and name == ""):
                    name = "engineering"
            # BF-910: a name, never a path; the refusal never echoes the value.
            if not is_standing_order_name(name):
                return ToolResult(error=_STANDING_ORDERS_NAME_REFUSAL)
            base = (self._orders_dir or standing_orders_dir()).resolve()
            names = standing_order_names(base)
            if name not in names:
                return ToolResult(
                    error="Standing orders not found for that name; available: "
                    + (", ".join(names) or "none")
                )
            # BF-910: the floor, the operator's read policy and a pinned,
            # link-refusing read, exactly as the verified source read does.
            snapshot = read_verified_file(
                base / f"{name}.md",
                protected_roots=protected_read_roots(self._runtime),
                exempt_roots=workspace_exempt_roots(self._runtime),
                permitted_roots=permitted_read_roots(self._runtime) or None,
            )
            # Path.read_text's UTF-8 and universal-newline output, as before.
            with io.TextIOWrapper(io.BytesIO(snapshot.data), encoding="utf-8", newline=None) as text:
                return ToolResult(output=text.read())
        except FileAccessDenied:
            return ToolResult(error=_STANDING_ORDERS_DENIED)
        except Exception as exc:
            kind = _exception_kind(exc)
            logger.warning("BF-910: standing_orders_lookup failed: %s", kind)
            return ToolResult(error=f"standing_orders_lookup failed: {kind}")


class SystemSelfModelTool:
    """AD-544: Snapshot of runtime topology."""

    tool_id: str = "system_self_model"
    name: str = "System Self Model"
    tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION
    description: str = "Return a compact runtime topology snapshot (pools, agents, departments)."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        try:
            ssm = getattr(self._runtime, "system_self_model", None)
            if ssm is not None and hasattr(ssm, "snapshot"):
                snap = ssm.snapshot()
                return ToolResult(output=snap)
            # Fallback: hand-built compact topology
            pools = []
            spawner = getattr(self._runtime, "spawner", None)
            if spawner is not None and hasattr(spawner, "list_pools"):
                pools = list(spawner.list_pools())
            registry = getattr(self._runtime, "registry", None)
            agent_count = len(registry.all()) if registry is not None and hasattr(registry, "all") else 0
            return ToolResult(
                output={
                    "pools": pools,
                    "agent_count": agent_count,
                }
            )
        except Exception as exc:
            return ToolResult(error=f"system_self_model failed: {exc}")


# --------------------------------------------------------------------------
# Write tools (Trust 0.3+ Lieutenant / WRITE)
# --------------------------------------------------------------------------


class WriteFileTool:
    """AD-544: Write a file (delegates to AD-302 FileWriterAgent semantics)."""

    tool_id: str = "write_file"
    name: str = "Write File"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "Write content to a file. Consensus-gated downstream."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "bytes_written": {"type": "integer"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    def resolve_effect_target(self, path: str) -> Path:
        """Resolve the concrete path this tool will write."""
        return _resolve_path(path).resolve(strict=False)

    def supports_strict_effect_target(self) -> bool:
        return _strict_native_target_supported()

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        path = params.get("path")
        content = params.get("content")
        if not path:
            return ToolResult(error="path is required")
        if content is None:
            return ToolResult(error="content is required")
        try:
            target = _resolve_path(str(path))
            strict_target = (context or {}).get("_strict_native_target")
            strict_root = (context or {}).get("_strict_native_root")
            if (
                isinstance(strict_target, str)
                and strict_target
                and isinstance(strict_root, str)
                and strict_root
            ):
                with _locked_native_target(
                    target,
                    Path(strict_target),
                    Path(strict_root),
                ) as locked:
                    locked.seek(0)
                    locked.write(str(content).encode("utf-8"))
                    locked.truncate()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
            return ToolResult(
                output={"path": str(path), "bytes_written": len(str(content))}
            )
        except Exception as exc:
            if (context or {}).get("_effect_dispatch_context") is not None:
                logger.warning(
                    "Strict native file write failed operation=write_file "
                    "reason_code=consumer_failed error_type=%s; broker will "
                    "retain correlation",
                    type(exc).__name__,
                )
                raise
            logger.warning("AD-544 WriteFileTool failed for path=%s: %s", path, exc)
            return ToolResult(error=f"write_file failed: {exc}")


class EditFileTool:
    """AD-544: In-place search/replace edit on an existing file."""

    tool_id: str = "edit_file"
    name: str = "Edit File"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "Replace text in an existing file (first-occurrence by default)."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "old_text", "new_text"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"replacements": {"type": "integer"}},
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    def resolve_effect_target(self, path: str) -> Path:
        """Resolve the concrete path this tool will edit."""
        return _resolve_path(path).resolve(strict=False)

    def supports_strict_effect_target(self) -> bool:
        return _strict_native_target_supported()

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        path = params.get("path")
        old = params.get("old_text")
        new = params.get("new_text")
        if not path:
            return ToolResult(error="path is required")
        if old is None or new is None:
            return ToolResult(error="old_text and new_text are required")
        replace_all = bool(params.get("replace_all", False))
        mutation_started = False
        try:
            target = _resolve_path(str(path))
            strict_target = (context or {}).get("_strict_native_target")
            strict_root = (context or {}).get("_strict_native_root")
            lock = (
                _locked_native_target(
                    target,
                    Path(strict_target),
                    Path(strict_root),
                    create=False,
                )
                if (
                    isinstance(strict_target, str)
                    and strict_target
                    and isinstance(strict_root, str)
                    and strict_root
                )
                else nullcontext(target)
            )
            with lock as locked:
                if (
                    isinstance(strict_target, str)
                    and strict_target
                    and isinstance(strict_root, str)
                    and strict_root
                ):
                    locked.seek(0)
                    text = locked.read().decode("utf-8")
                else:
                    text = locked.read_text(encoding="utf-8")
                if replace_all:
                    count = text.count(str(old))
                    updated = text.replace(str(old), str(new))
                else:
                    if str(old) not in text:
                        count = 0
                        updated = text
                    else:
                        updated = text.replace(str(old), str(new), 1)
                        count = 1
                if count > 0:
                    if (
                        isinstance(strict_target, str)
                        and strict_target
                        and isinstance(strict_root, str)
                        and strict_root
                    ):
                        locked.seek(0)
                        mutation_started = True
                        locked.write(updated.encode("utf-8"))
                        locked.truncate()
                    else:
                        mutation_started = True
                        locked.write_text(updated, encoding="utf-8")
            return ToolResult(output={"replacements": count, "path": str(path)})
        except FileNotFoundError:
            if (context or {}).get("_effect_dispatch_context") is not None:
                if mutation_started:
                    raise
                from probos.execution.effect_broker import NoEffectFailure

                raise NoEffectFailure("file_not_found")
            return ToolResult(error=f"File not found: {path}")
        except Exception as exc:
            if (context or {}).get("_effect_dispatch_context") is not None:
                raise
            return ToolResult(error=f"edit_file failed: {exc}")


# --------------------------------------------------------------------------
# Shell tools (Trust 0.5+ Commander / WRITE)
# --------------------------------------------------------------------------


class RunCommandTool:
    """AD-544: Run a shell command via ShellCommandAgent semantics."""

    tool_id: str = "run_command"
    name: str = "Run Command"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "Run a shell command and return stdout/stderr/exit_code."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number"},
            "working_directory": {"type": "string"},
        },
        "required": ["command"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
        },
    }

    def __init__(
        self,
        runtime: "ProbOSRuntime",
        *,
        command_env_passthrough: tuple[str, ...] = (),
        command_policy_gate: CommandPolicyGate | None = None,
        command_escalations: CommandEscalations | None = None,
    ) -> None:
        self._runtime = runtime
        # BF-890 (#1529): names from execution.command_env_passthrough, injected
        # at registration; input_schema declares no such parameter.
        self._command_env_passthrough: tuple[str, ...] = tuple(command_env_passthrough)
        # AD-1328 S2a (#1530): the runtime's command policy (ProbOSRuntime.command_policy_gate),
        # injected at registration. None: no policy.
        self._command_policy_gate = command_policy_gate
        # AD-1328 S2b (#1530): the runtime's approval route for an escalated command
        # (runtime.command_escalations), injected at registration. None: S2a's refusal.
        self._command_escalations = command_escalations

    async def _escalate(
        self, verdict: CommandGateVerdict, command: str, context: dict[str, Any] | None,
    ) -> tuple[CommandGateVerdict, str | None]:
        """AD-1328 S2b: the verdict to record and the refusal to return for a command the
        policy does not run on its own. ``forbid``, and an ``escalate`` with no approval
        route, keep the S2a refusal; an ``escalate`` goes to ``CommandEscalations``."""
        escalations = self._command_escalations
        if verdict.decision != "escalate" or escalations is None:
            return verdict, verdict.refusal_message
        outcome = await escalations.resolve(verdict, command=command, context=context)
        return outcome.verdict, outcome.message

    def _policy_verdict(self, command: Any, cwd: object) -> CommandGateVerdict | None:
        """AD-1328 S2a: the policy's verdict on ``command`` as this tool spawns it, or None
        with no policy (no gate, or no rules), in which case nothing else is done and
        ``command`` is not read. ``judge`` raises for anything but an exact ``str``, so the
        object judged is the object spawned (repair r1, F3)."""
        gate = self._command_policy_gate
        if gate is None or not gate.configured:
            return None
        # The child's PATH and PATHEXT, from the owner that builds the child's environment below.
        child_env = build_command_env(self._command_env_passthrough)
        return gate.judge(
            command,
            site="run_command_tool",
            search_path=child_env.get("PATH"),
            cwd=cwd if type(cwd) is str else None,
            pathext=child_env.get("PATHEXT"),
        )

    def command_policy_preflight(self, params: dict[str, Any]) -> str:
        """AD-1328 S2a: the AD-1316 shell adapter's question, asked before the broker reserves
        the effect. The policy's reason code for refusing this call, or "" when it does not
        refuse it (the adapter still refuses an unproven shell)."""
        command = params.get("command") if type(params) is dict else None
        if type(command) is not str or not command.strip():
            return ""
        try:
            verdict = self._policy_verdict(command, params.get("working_directory"))
        except Exception:
            logger.warning(
                "AD-1328: the command policy could not judge a run_command call before broker "
                "admission; it is refused", exc_info=True,
            )
            return COMMAND_POLICY_UNAVAILABLE
        return "" if verdict is None or verdict.runs else verdict.denial_reason

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        import asyncio as _asyncio
        import shlex
        import sys

        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        command = params.get("command", "")
        if not command or not str(command).strip():
            return ToolResult(error="command is required")
        timeout = float(params.get("timeout", 30.0))
        cwd = params.get("working_directory")
        verdict: CommandGateVerdict | None = None
        try:
            # AD-1328 S2a (#1530): the command policy judges the command before it runs. With
            # no policy the verdict is None and nothing else here changes. A judgement that
            # raises lands in the handler below: the command is not run. Repair r1 (review F3):
            # the policy judges the object itself and the same object is spawned; a command that
            # is not exactly a str raises in judge. With no policy it is converted as before.
            verdict = self._policy_verdict(command, cwd)
            if verdict is not None and not verdict.runs:
                # AD-1328 S2b (#1530): an escalation goes to the chain of command. It runs
                # here only under the Captain's approval in this scope, recorded first.
                # ``command`` is the exact str judge accepted (S2a repair r1, F3), so the
                # filed text, the judged text and the spawned text are one object; a raise
                # lands in the handler below with the escalate record and nothing runs.
                verdict, refusal = await self._escalate(verdict, command, context)
                if refusal is not None or not verdict.runs:
                    return ToolResult(
                        error=refusal or verdict.refusal_message,
                        metadata=policy_result_metadata(verdict),
                    )
            # Cross-platform: use shell=True via create_subprocess_shell
            proc = await _asyncio.create_subprocess_shell(
                str(command) if verdict is None else command,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                cwd=cwd,
                # BF-890 (#1529): an allowlisted environment, not the runtime's.
                env=build_command_env(self._command_env_passthrough),
                # BF-893 (#1544): the command's whole tree can be ended on a timeout.
                **process_tree_popen_kwargs(),
            )
            tree = ProcessTree.attach(proc)
            try:
                stdout_b, stderr_b = await _asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except _asyncio.TimeoutError:
                tree.kill()
                return ToolResult(
                    error=f"run_command timed out after {timeout}s",
                    metadata=policy_result_metadata(verdict),
                )
            except _asyncio.CancelledError:
                tree.kill()  # BF-893: an enclosing timeout or cancellation must not leave the tree running
                raise
            finally:
                tree.close()
            stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
            return ToolResult(
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode if proc.returncode is not None else -1,
                },
                metadata=policy_result_metadata(verdict),
            )
        except Exception as exc:
            logger.warning("AD-544 RunCommandTool failed for command=%s: %s", command, exc)
            # AD-1328 S2a repair r1 (review F2): a failure after the policy judged the command keeps
            # its decision; before that, and with no policy, the metadata stays empty as before.
            return ToolResult(error=f"run_command failed: {exc}", metadata=policy_result_metadata(verdict))


# --------------------------------------------------------------------------
# Registration helper
# --------------------------------------------------------------------------


def register_native_swe_tools(
    registry: "ToolRegistry",
    runtime: "ProbOSRuntime",
    *,
    command_env_passthrough: tuple[str, ...] = (),
    command_policy_gate: CommandPolicyGate | None = None,
    command_escalations: CommandEscalations | None = None,
) -> int:
    """AD-544: Register all 12 native SWE tools into the registry.

    Returns count registered. Idempotent — existing entries are replaced
    (mirrors ToolRegistry.register last-write-wins semantics).
    """
    read_perms = {
        "ensign": "read",
        "lieutenant": "read",
        "commander": "read",
        "senior_officer": "full",
    }
    write_perms = {
        "ensign": "none",
        "lieutenant": "write",
        "commander": "write",
        "senior_officer": "full",
    }
    shell_perms = {
        "ensign": "none",
        "lieutenant": "none",
        "commander": "write",
        "senior_officer": "full",
    }
    entries: list[tuple[Tool, dict[str, str]]] = [
        (ReadFileTool(runtime), read_perms),
        (ListFilesTool(runtime), read_perms),
        (CodebaseQueryTool(runtime), read_perms),
        (CodebaseFindCallersTool(runtime), read_perms),
        (CodebaseFindTestsTool(runtime), read_perms),
        (CodebaseGetImportsTool(runtime), read_perms),
        (CodebaseReadSourceTool(runtime), read_perms),
        (StandingOrdersLookupTool(runtime), read_perms),
        (SystemSelfModelTool(runtime), read_perms),
        (WriteFileTool(runtime), write_perms),
        (EditFileTool(runtime), write_perms),
        # BF-890: the operator's declared names (execution.command_env_passthrough).
        (
            RunCommandTool(
                runtime,
                command_env_passthrough=command_env_passthrough,
                # AD-1328 S2a: the runtime's command policy.
                command_policy_gate=command_policy_gate,
                # AD-1328 S2b: its approval route for an escalated command.
                command_escalations=command_escalations,
            ),
            shell_perms,
        ),
    ]
    count = 0
    for tool, perms in entries:
        registry.register(
            tool,
            domain="engineering",
            provider="swe_harness",
            tags=["native", "swe", tool.tool_id],
            default_permissions=perms,
        )
        count += 1
    logger.info("AD-544: Registered %d native SWE tools into registry", count)
    return count
