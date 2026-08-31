"""AD-544: Native SWE tool suite — 12 ``Tool``-Protocol adapters wrapping
existing ProbOS capabilities (FileReaderAgent, FileWriterAgent, ShellCommandAgent,
FileSearchAgent, CodebaseIndex, standing-orders manuals, system self-model).

Each adapter satisfies AD-423a ``Tool`` Protocol. ``register_native_swe_tools``
batch-registers all twelve into the AD-423a/b ``ToolRegistry`` under the
``engineering`` domain with rank-keyed ``default_permissions`` aligned to
AD-423b's permission ladder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from probos.tools.protocol import Tool, ToolResult, ToolType

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_path(path: str) -> Path:
    """Resolve a user-supplied path against project root if relative."""
    p = Path(path)
    return p if p.is_absolute() else (_PROJECT_ROOT / p)


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

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        path = params.get("path")
        if not path:
            return ToolResult(error="path is required")
        try:
            from probos.security.file_access import resolve_for_runtime

            target = resolve_for_runtime(
                str(path), self._runtime, relative_base=_PROJECT_ROOT
            )
        except Exception as exc:
            return ToolResult(error=f"read_file refused: {exc}")
        try:
            text = target.read_text(encoding="utf-8")
            offset = params.get("offset")
            limit = params.get("limit")
            if offset is not None or limit is not None:
                lines = text.splitlines()
                start = int(offset or 0)
                end = start + int(limit) if limit is not None else len(lines)
                text = "\n".join(lines[start:end])
            return ToolResult(output=text)
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except Exception as exc:
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
                "AD-544 ListFilesTool failed for pattern=%s path=%s: %s",
                pattern,
                path,
                exc,
            )
            return ToolResult(error=f"list_files failed: {exc}")


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

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        path = params.get("file_path")
        if not path:
            return ToolResult(error="file_path is required")
        try:
            target = _resolve_path(str(path))
            text = target.read_text(encoding="utf-8")
            start = params.get("start_line")
            end = params.get("end_line")
            if start is not None or end is not None:
                lines = text.splitlines()
                s = max(0, int(start or 1) - 1)
                e = int(end) if end is not None else len(lines)
                text = "\n".join(lines[s:e])
            return ToolResult(output=text)
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


class StandingOrdersLookupTool:
    """AD-544: Read a standing-orders manual file."""

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

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        scope = params.get("scope")
        if scope not in _STANDING_ORDERS_SCOPES:
            return ToolResult(
                error="scope must be one of " + "|".join(_STANDING_ORDERS_SCOPES)
            )
        base = _PROJECT_ROOT / "config" / "standing_orders"
        try:
            if scope == "ship":
                target = base / "ship.md"
            elif scope == "department":
                dept = params.get("department") or "engineering"
                target = base / "departments" / f"{dept}.md"
            else:
                dept = params.get("department") or "engineering"
                target = base / "departments" / f"{dept}.md"
            if not target.exists():
                return ToolResult(error=f"Standing orders not found: {target.name}")
            return ToolResult(output=target.read_text(encoding="utf-8"))
        except Exception as exc:
            return ToolResult(error=f"standing_orders_lookup failed: {exc}")


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

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        path = params.get("path")
        content = params.get("content")
        if not path:
            return ToolResult(error="path is required")
        if content is None:
            return ToolResult(error="content is required")
        try:
            target = _resolve_path(str(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            return ToolResult(
                output={"path": str(path), "bytes_written": len(str(content))}
            )
        except Exception as exc:
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

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        path = params.get("path")
        old = params.get("old_text")
        new = params.get("new_text")
        if not path:
            return ToolResult(error="path is required")
        if old is None or new is None:
            return ToolResult(error="old_text and new_text are required")
        replace_all = bool(params.get("replace_all", False))
        try:
            target = _resolve_path(str(path))
            text = target.read_text(encoding="utf-8")
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
                target.write_text(updated, encoding="utf-8")
            return ToolResult(output={"replacements": count, "path": str(path)})
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except Exception as exc:
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

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        import asyncio as _asyncio
        import shlex
        import sys

        command = params.get("command", "")
        if not command or not str(command).strip():
            return ToolResult(error="command is required")
        timeout = float(params.get("timeout", 30.0))
        cwd = params.get("working_directory")
        try:
            # Cross-platform: use shell=True via create_subprocess_shell
            proc = await _asyncio.create_subprocess_shell(
                str(command),
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout_b, stderr_b = await _asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except _asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return ToolResult(error=f"run_command timed out after {timeout}s")
            stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
            return ToolResult(
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode if proc.returncode is not None else -1,
                }
            )
        except Exception as exc:
            logger.warning("AD-544 RunCommandTool failed for command=%s: %s", command, exc)
            return ToolResult(error=f"run_command failed: {exc}")


# --------------------------------------------------------------------------
# Registration helper
# --------------------------------------------------------------------------


def register_native_swe_tools(
    registry: "ToolRegistry", runtime: "ProbOSRuntime"
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
        (RunCommandTool(runtime), shell_perms),
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
