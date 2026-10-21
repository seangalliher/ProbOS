"""CopilotBuilderAdapter — Visiting officer integration via GitHub Copilot SDK (AD-351/352).

Wraps the Copilot SDK to execute build tasks as a visiting officer.  The adapter
is NOT a CognitiveAgent — it's an external system wrapper (like ChannelAdapter
for Discord).  Creates a CopilotClient, injects ProbOS Standing Orders as system
instructions, registers MCP tools, translates BuildSpec into a session prompt,
and captures output in native file-block format.

The SDK import is guarded with try/except — the package is optional.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

from probos.cognitive.builder_paths import builder_write_refusal
from probos.cognitive.standing_orders import (
    is_standing_order_name,
    standing_order_names,
    standing_orders_dir,
)
from probos.security.file_access import (
    FileAccessDenied,
    permitted_read_roots,
    protected_read_roots,
    read_verified_file,
    workspace_exempt_roots,
)
from probos.repository_instructions import (
    append_repository_instructions,
    discover_build_repository_instructions,
    instruction_read_policy,
    repository_instruction_directory,
)
if TYPE_CHECKING:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.codebase_index import CodebaseIndex
    from probos.runtime import ProbOSRuntime

_SDK_AVAILABLE = False
try:
    from copilot import CopilotClient, PermissionRequestResult, Tool, ToolResult  # type: ignore[import-untyped]
    from copilot.generated.session_events import SessionEventType  # type: ignore[import-untyped]

    _SDK_AVAILABLE = True
except ImportError:
    # Minimal fallback so tool handlers work in tests without the SDK
    class ToolResult:  # type: ignore[no-redef]
        def __init__(self, *, text_result_for_llm: str = "") -> None:
            self.text_result_for_llm = text_result_for_llm

    @dataclass
    class PermissionRequestResult:  # type: ignore[no-redef]
        """BF-896: stand-in with the SDK's ``kind`` field; used only without the SDK."""

        kind: str = "denied-no-approval-rule-and-could-not-request-from-user"

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# BF-910: fixed replies for the visiting session's standing_orders_lookup; none
# echoes the caller's value or a path, and none contains a dot.
_STANDING_ORDERS_NAME_REFUSAL = (
    "department must name one standing-orders file: 1 to 64 ASCII letters, "
    "digits, '_' or '-', for example 'engineering'"
)
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)


def _standing_orders_reply(
    invocation: Any, orders_dir: Path | None, runtime: ProbOSRuntime | None
) -> Any:
    """BF-910: the reply to the visiting session's ``standing_orders_lookup``.

    ``CopilotBuilderAdapter._handle_standing_orders`` is the registered handler and
    passes its ``orders_dir`` and ``runtime``. The body sits outside the class so the
    class stays under the repository's 500-line SRP review trigger (BF-910 D16).
    """
    args = getattr(invocation, "arguments", None) or {}
    department = args.get("department", "") if isinstance(args, dict) else ""
    if not department:
        return ToolResult(text_result_for_llm="No department specified")
    # BF-910: a name from the loader's flat directory, never a path.
    if not is_standing_order_name(department):
        return ToolResult(text_result_for_llm=_STANDING_ORDERS_NAME_REFUSAL)
    try:
        base = (orders_dir or standing_orders_dir()).resolve()
        names = standing_order_names(base)
        if department not in names:
            return ToolResult(
                text_result_for_llm="No standing orders found for that department; available: "
                + (", ".join(names) or "none")
            )
        # BF-910: the BF-758 floor, the operator's read policy and a pinned,
        # link-refusing read. runtime None (dispatcher route) is the
        # platform-data-dir floor with no policy.
        snapshot = read_verified_file(
            base / f"{department}.md",
            protected_roots=protected_read_roots(runtime),
            exempt_roots=workspace_exempt_roots(runtime),
            permitted_roots=permitted_read_roots(runtime) or None,
        )
        # Path.read_text(encoding="utf-8", errors="replace")'s output, as before.
        with io.TextIOWrapper(
            io.BytesIO(snapshot.data), encoding="utf-8", errors="replace", newline=None,
        ) as text:
            return ToolResult(text_result_for_llm=text.read())
    except FileAccessDenied:
        return ToolResult(text_result_for_llm=_STANDING_ORDERS_DENIED)
    except Exception as exc:
        logger.warning("BF-910: visiting standing_orders_lookup read failed: %s", type(exc).__name__)
        return ToolResult(text_result_for_llm=f"standing_orders_lookup failed: {type(exc).__name__}")

# ── Visiting Builder identity ──────────────────────────────────────────────

_VISITING_BUILDER_INSTRUCTIONS = (
    "You are the ProbOS Visiting Builder — a visiting officer from the Copilot fleet, "
    "operating under ProbOS Standing Orders. You write code for ProbOS build tasks.\n\n"
    "OUTPUT FORMAT:\n"
    "For new files, use:\n"
    "===FILE: path/relative/to/project===\n"
    "file content here\n"
    "===END FILE===\n\n"
    "For modifications to existing files, use:\n"
    "===MODIFY: path/relative/to/project===\n"
    "===SEARCH===\n"
    "exact text to find\n"
    "===REPLACE===\n"
    "replacement text\n"
    "===END REPLACE===\n"
    "===END MODIFY===\n\n"
    "WORKING ENVIRONMENT:\n"
    "- You are operating in an ISOLATED temp directory, not the project root\n"
    "- Do NOT explore the filesystem (no ls, find, tree, cat of project files)\n"
    "- All project context is available through your MCP tools (codebase_query, codebase_read_source, etc.)\n"
    "- Write all output files directly to the current directory using the paths from the build spec\n"
    "- Shell commands, and reads or writes outside the current directory, are denied by the session's permission policy\n"
    "- For existing files that need modification, their current content is provided in the prompt below\n"
    "- Source files go under src/probos/ — test files go under tests/\n\n"
    "PROJECT STRUCTURE:\n"
    "- Source code: src/probos/ (packages: cognitive/, mesh/, medical/, api.py, shell.py, etc.)\n"
    "- Tests: tests/ (flat layout: tests/test_builder_agent.py, tests/test_trust.py, etc.)\n"
    "- Config: config/ (standing_orders/, extension_profiles/)\n"
    "- All imports use absolute paths: from probos.cognitive.builder import BuilderAgent\n"
    "- Test files are named: test_{module_name}.py\n\n"
    "RULES:\n"
    "- Follow existing codebase patterns — use the codebase_query tool to find them\n"
    "- Every public function needs a test\n"
    "- Use full probos.* import paths, never relative imports\n"
    "- SEARCH blocks must match EXACTLY — character-for-character\n"
    "- Keep SEARCH blocks small — just enough context to be unique\n"
    "- Order SEARCH/REPLACE pairs top-to-bottom in the file\n"
    "- Use pytest.mark.asyncio for async test methods\n"
    "- Before writing test fixtures, check the target class __init__ signature\n"
)


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class CopilotBuildResult:
    """Result from a visiting Builder Copilot session."""

    success: bool = False
    file_blocks: list[dict[str, Any]] = field(default_factory=list)
    raw_output: str = ""
    error: str = ""
    session_id: str = ""
    model_used: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────


def _classify_provider(model_id: str) -> str:
    """Classify a model ID to its provider name."""
    model_lower = model_id.lower()
    if "claude" in model_lower:
        return "Anthropic"
    if "gpt" in model_lower:
        return "OpenAI"
    if "gemini" in model_lower:
        return "Google"
    if "qwen" in model_lower or "deepseek" in model_lower:
        return "Local/OSS"
    return "Unknown"


# ── Adapter ────────────────────────────────────────────────────────────────


def _normalize_sdk_path(raw_path: str, cwd: Path) -> str:
    """Normalize a file path from the SDK event to a cwd-relative path (AD-354).

    The SDK may report paths as:
    - Relative with forward slashes:  ``src/test.py``
    - Absolute Windows paths:  ``D:\\tmp\\build123\\src\\test.py``
    - Absolute POSIX paths:  ``/tmp/build123/src/test.py``
    - Mixed separators:  ``src\\test.py``

    Returns a forward-slash relative path suitable for file_blocks.
    """
    # Normalize separators
    normalized = raw_path.replace("\\", "/")

    p = Path(normalized)
    if p.is_absolute():
        try:
            rel = p.relative_to(cwd)
            return str(rel).replace("\\", "/")
        except ValueError:
            # Absolute but not under cwd — use as-is (shouldn't happen, but safe)
            return normalized
    # Already relative — just normalize separators
    return normalized


# ── BF-896: session confinement ────────────────────────────────────────────

_PERMISSION_APPROVED = "approved"
_PERMISSION_DENIED = "denied-by-rules"  # a denial kind in SDK 0.1.30 and 0.1.32
# 0.1.32 sends a dataclass (snake_case attributes); 0.1.30 a wire dict (camelCase keys).
_PATH_FIELDS = ("file_name", "fileName", "path")
_POSSIBLE_PATH_FIELDS = ("possible_paths", "possiblePaths")
_TOOL_NAME_FIELDS = ("tool_name", "toolName")


def _request_field(request: Any, name: str) -> Any:
    """One field of a permission request, from either SDK shape."""
    if isinstance(request, dict):
        return request.get(name)
    return getattr(request, name, None)


def _request_kind(request: Any) -> str | None:
    """The request's kind as an exact ``str`` (0.1.32 sends an ``Enum``), or None."""
    kind = _request_field(request, "kind")
    if isinstance(kind, Enum):
        kind = kind.value
    return kind if type(kind) is str else None


def _session_root(session_dir: Any) -> tuple[str, str] | None:
    """(real path, case-folded real path) of an existing, absolute session directory, or None."""
    if type(session_dir) is not str or not session_dir or "\x00" in session_dir:
        return None
    if not os.path.isabs(session_dir):
        return None  # a relative name would resolve against whatever the process cwd is
    try:
        real = os.path.realpath(session_dir)
        if not os.path.isdir(real):
            return None
        return real, os.path.normcase(real)
    except (OSError, ValueError):
        return None


def _session_relative(root: tuple[str, str], raw: Any) -> str | None:
    """The forward-slash path *raw* names strictly inside the session root, or None.

    Fails closed: a non-string, an empty value, a NUL, a ``..`` component, a ``:``
    anywhere but an absolute path's drive (an NTFS stream or a drive-relative form),
    and anything that resolves (symlinks followed) outside the root, or to the root
    itself, are all None.
    """
    if type(raw) is not str or not raw or "\x00" in raw:
        return None
    if ".." in raw.replace("\\", "/").split("/"):
        return None
    drive, tail = os.path.splitdrive(raw)
    if ":" in tail or (drive and not os.path.isabs(raw)):
        return None
    real_root, folded_root = root
    try:
        candidate = raw if os.path.isabs(raw) else os.path.join(real_root, raw)
        real = os.path.realpath(candidate)
        folded = os.path.normcase(real)
        if folded == folded_root or os.path.commonpath([folded_root, folded]) != folded_root:
            return None
        return os.path.relpath(real, real_root).replace("\\", "/")
    except (OSError, ValueError):
        return None


def _permission_verdict(
    request: Any, root: tuple[str, str] | None, tools: frozenset[str],
) -> bool:
    """True only for a request the session policy approves (see the factory)."""
    kind = _request_kind(request)
    if kind == "custom-tool":
        names = [n for n in (_request_field(request, f) for f in _TOOL_NAME_FIELDS) if n is not None]
        return bool(names) and all(type(n) is str and n in tools for n in names)
    if kind not in ("write", "read") or root is None:
        return False
    targets: list[Any] = [
        value for value in (_request_field(request, f) for f in _PATH_FIELDS) if value is not None
    ]
    for name in _POSSIBLE_PATH_FIELDS:
        extra = _request_field(request, name)
        if extra is None:
            continue
        if not isinstance(extra, (list, tuple)):
            return False
        targets.extend(extra)
    if not targets:
        return False
    for raw in targets:
        rel = _session_relative(root, raw)
        if rel is None:
            return False
        if kind == "write" and builder_write_refusal(rel) is not None:
            return False
    return True


def build_session_permission_handler(
    session_dir: Any, tool_names: Iterable[Any],
) -> Callable[..., Any]:
    """BF-896: the permission policy of a visiting build session, deny by default.

    Approves only: a ``write`` whose every named target lies strictly inside
    *session_dir* and passes the builder's lexical write rules
    (``builder_write_refusal``); a ``read`` strictly inside *session_dir*; a
    ``custom-tool`` call to one of *tool_names* (the adapter's registered tools).
    Every other kind (``shell``, ``url``, ``mcp``, ``memory``, anything new), a
    request it cannot parse, and any error are denied. Never raises: an unusable
    *session_dir* denies every path request.
    """
    root = _session_root(session_dir)
    try:
        allowed = frozenset(name for name in tool_names if type(name) is str)
    except Exception:
        allowed = frozenset()

    def handler(request: Any, invocation: Any = None) -> Any:
        try:
            label = _request_kind(request)
            approved = _permission_verdict(request, root, allowed)
        except Exception:
            label, approved = "unparsed", False
            logger.warning("BF-896: a permission request could not be evaluated; denied", exc_info=True)
        if not approved:
            logger.info("BF-896: visiting build session denied a %s permission request", label)
        return PermissionRequestResult(kind=_PERMISSION_APPROVED if approved else _PERMISSION_DENIED)

    return handler


def seed_session_directory(session_dir: str, files: Mapping[str, str]) -> dict[str, str]:
    """BF-896: copy a build's existing files into its session directory.

    Writes each non-empty entry at its session-relative path; an empty entry (a file
    that does not exist yet) is kept in the result but not written. A key that does
    not name a path strictly inside *session_dir* is logged and dropped. Returns the
    entries keyed by session-relative path, which is the key the adapter's scan
    compares against. Raises ValueError when *session_dir* is not an existing
    directory.
    """
    root = _session_root(session_dir)
    if root is None:
        raise ValueError(f"BF-896: session directory {session_dir!r} is not an existing directory")
    seeded: dict[str, str] = {}
    for raw, content in files.items():
        if type(content) is not str:
            continue
        rel = _session_relative(root, raw)
        if rel is None:
            logger.warning("BF-896: not seeding %r: it names no path inside the session directory", raw)
            continue
        seeded[rel] = content
        if not content:
            continue
        dest = Path(root[0]) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return seeded


class CopilotBuilderAdapter:
    """Wraps the GitHub Copilot SDK to execute build tasks as a visiting officer.

    The adapter:
    1. Creates a CopilotClient with ProbOS's Standing Orders as system instructions
    2. Registers ProbOS MCP tools (CodebaseIndex, SystemSelfModel, StandingOrders)
    3. Translates a BuildSpec into a Copilot session prompt
    4. Captures file changes from the session output
    5. Returns file blocks in the same format as the native Builder
    """

    def __init__(
        self,
        *,
        codebase_index: CodebaseIndex | None = None,
        runtime: ProbOSRuntime | None = None,
        model: str = "claude-sonnet-5.5",
        cwd: str = "",
        github_token: str = "",
        instruction_work_dir: str | None = None,
        orders_dir: Path | None = None,
    ) -> None:
        self._codebase_index = codebase_index
        # BF-910: None reads the loader's standing-orders directory at each call; tests inject one.
        self._orders_dir = orders_dir
        self._runtime = runtime
        self._model = model
        # BF-896: repository instructions are discovered from instruction_work_dir
        # (the worktree on the queued route); the session runs in cwd. A caller that
        # names only cwd keeps AD-1200's behaviour (both the same directory).
        self._instruction_work_dir = cwd if instruction_work_dir is None else instruction_work_dir
        self._cwd = cwd or str(_PROJECT_ROOT)
        # BF-896: execute() runs a session only in a directory its caller named;
        # the _PROJECT_ROOT fallback above is the client cwd for start() alone.
        self._session_dir_given = bool(cwd)
        self._github_token = github_token
        self._client: Any | None = None
        self._started = False

    @classmethod
    def is_available(cls) -> bool:
        """Check if the Copilot SDK is installed."""
        return _SDK_AVAILABLE

    async def start(self) -> None:
        """Initialize the CopilotClient.  Call once at startup."""
        if not _SDK_AVAILABLE:
            raise RuntimeError("github-copilot-sdk not installed")
        client_opts: dict[str, Any] = {
            "cwd": self._cwd,
            "log_level": "warning",
        }
        if self._github_token:
            client_opts["github_token"] = self._github_token
        else:
            client_opts["use_logged_in_user"] = True
        self._client = CopilotClient(client_opts)
        await self._client.start()
        self._started = True

    async def stop(self) -> None:
        """Shut down the CopilotClient."""
        if self._client and self._started:
            await self._client.stop()
        self._started = False

    async def list_available_models(self) -> list[dict[str, str]]:
        """List all models available through the Copilot SDK.

        Returns a list of dicts with keys: id, provider, source, hosting.
        Requires the adapter to be started.
        """
        if not self._started or not self._client:
            return []
        try:
            raw_models = await self._client.list_models()
            results = []
            for m in raw_models:
                model_id = getattr(m, "id", "") or str(m)
                results.append({
                    "id": model_id,
                    "provider": _classify_provider(model_id),
                    "source": "GitHub Copilot",
                    "hosting": "external",
                })
            return results
        except Exception:
            logger.debug("Failed to list Copilot SDK models", exc_info=True)
            return []

    # ── System message ─────────────────────────────────────────────────

    def _compose_system_message(self) -> dict[str, Any]:
        """Build the system message for the Copilot session.

        Uses compose_instructions() to assemble the full Standing Orders
        hierarchy, matching what the native Builder receives.
        """
        from probos.cognitive.standing_orders import compose_instructions

        composed = compose_instructions(
            agent_type="builder",
            hardcoded_instructions=_VISITING_BUILDER_INSTRUCTIONS,
        )
        return {"mode": "replace", "content": composed}

    # ── MCP tools (AD-352) ─────────────────────────────────────────────

    def _build_mcp_tools(self) -> list[Any]:
        """Build the MCP tools list for the Copilot session.

        Exposes ProbOS internals as tools the visiting Builder can call.
        """
        if not _SDK_AVAILABLE:
            return []

        tools: list[Any] = []

        # Always include standing orders lookup
        tools.append(Tool(
            name="standing_orders_lookup",
            description="Look up the department protocols for a given department (engineering, science, medical, security, bridge).",
            parameters={
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "Department name"},
                },
                "required": ["department"],
            },
            handler=self._handle_standing_orders,
        ))

        # CodebaseIndex tools (if available)
        if self._codebase_index is not None:
            tools.append(Tool(
                name="codebase_query",
                description="Search the ProbOS codebase for files, agents, methods, and layers matching a concept keyword. Returns matching files, agents, and methods.",
                parameters={
                    "type": "object",
                    "properties": {
                        "concept": {
                            "type": "string",
                            "description": "The concept or keyword to search for (e.g., 'trust', 'HebbianRouter', 'pool health')",
                        },
                    },
                    "required": ["concept"],
                },
                handler=self._handle_codebase_query,
            ))
            tools.append(Tool(
                name="codebase_find_callers",
                description="Find all files that call/reference a given method name in the ProbOS codebase.",
                parameters={
                    "type": "object",
                    "properties": {
                        "method_name": {"type": "string", "description": "The method name to find callers of"},
                    },
                    "required": ["method_name"],
                },
                handler=self._handle_find_callers,
            ))
            tools.append(Tool(
                name="codebase_get_imports",
                description="Get the internal probos modules that a given source file imports.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Relative path to the source file (e.g., 'probos/cognitive/builder.py')"},
                    },
                    "required": ["file_path"],
                },
                handler=self._handle_get_imports,
            ))
            tools.append(Tool(
                name="codebase_find_tests",
                description="Find test files for a given source file, by naming convention.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Relative path to the source file"},
                    },
                    "required": ["file_path"],
                },
                handler=self._handle_find_tests,
            ))
            tools.append(Tool(
                name="codebase_read_source",
                description="Read the source code of a file in the ProbOS codebase. Can read specific line ranges.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Relative path to the file"},
                        "start_line": {"type": "integer", "description": "Optional start line (1-indexed)"},
                        "end_line": {"type": "integer", "description": "Optional end line (1-indexed)"},
                    },
                    "required": ["file_path"],
                },
                handler=self._handle_read_source,
            ))

        # SystemSelfModel tool (if runtime available)
        if self._runtime is not None:
            tools.append(Tool(
                name="system_self_model",
                description="Get the current ProbOS system topology: pools, agents, departments, health signals.",
                parameters={"type": "object", "properties": {}},
                handler=self._handle_system_self_model,
            ))

        return tools

    # ── Tool handlers ──────────────────────────────────────────────────

    async def _handle_codebase_query(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        concept = args.get("concept", "") if isinstance(args, dict) else ""
        if not self._codebase_index or not concept:
            return ToolResult(text_result_for_llm="CodebaseIndex not available")
        result = self._codebase_index.query(concept)
        return ToolResult(text_result_for_llm=json.dumps(result, indent=2, default=str))

    async def _handle_find_callers(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        method_name = args.get("method_name", "") if isinstance(args, dict) else ""
        if not self._codebase_index or not method_name:
            return ToolResult(text_result_for_llm="CodebaseIndex not available")
        result = self._codebase_index.find_callers(method_name)
        return ToolResult(text_result_for_llm=json.dumps(result, indent=2, default=str))

    async def _handle_get_imports(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        file_path = args.get("file_path", "") if isinstance(args, dict) else ""
        if not self._codebase_index or not file_path:
            return ToolResult(text_result_for_llm="CodebaseIndex not available")
        result = self._codebase_index.get_imports(file_path)
        return ToolResult(text_result_for_llm=json.dumps(result, indent=2, default=str))

    async def _handle_find_tests(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        file_path = args.get("file_path", "") if isinstance(args, dict) else ""
        if not self._codebase_index or not file_path:
            return ToolResult(text_result_for_llm="CodebaseIndex not available")
        result = self._codebase_index.find_tests_for(file_path)
        return ToolResult(text_result_for_llm=json.dumps(result, indent=2, default=str))

    async def _handle_read_source(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        file_path = args.get("file_path", "") if isinstance(args, dict) else ""
        if not self._codebase_index or not file_path:
            return ToolResult(text_result_for_llm="CodebaseIndex not available")
        start_line = args.get("start_line") if isinstance(args, dict) else None
        end_line = args.get("end_line") if isinstance(args, dict) else None
        result = self._codebase_index.read_source(file_path, start_line, end_line)
        return ToolResult(text_result_for_llm=result or "(empty or not found)")

    async def _handle_system_self_model(self, invocation: Any) -> Any:
        if not self._runtime:
            return ToolResult(text_result_for_llm="Runtime not available")
        self_model = self._runtime._build_system_self_model()
        return ToolResult(text_result_for_llm=self_model.to_context())

    async def _handle_standing_orders(self, invocation: Any) -> Any:
        # BF-910 (D16): the registered handler; the reply is _standing_orders_reply's.
        return _standing_orders_reply(invocation, self._orders_dir, self._runtime)

    # ── Prompt construction ────────────────────────────────────────────

    def _build_prompt(self, spec: BuildSpec, file_contents: dict[str, str]) -> str:
        """Translate a BuildSpec into a prompt for the Copilot session."""
        parts: list[str] = []

        parts.append(f"# Build Task: {spec.title}")
        if spec.ad_number:
            parts.append(f"AD Number: AD-{spec.ad_number}")
        parts.append("")
        parts.append("## Description")
        parts.append(spec.description)
        parts.append("")

        if spec.target_files:
            parts.append("## Target Files")
            for f in spec.target_files:
                parts.append(f"- {f}")
            parts.append("")

        if spec.test_files:
            parts.append("## Test Files")
            for f in spec.test_files:
                parts.append(f"- {f}")
            parts.append("")

        if spec.constraints:
            parts.append("## Constraints")
            for c in spec.constraints:
                parts.append(f"- {c}")
            parts.append("")

        # Include existing file contents
        for path, content in file_contents.items():
            if path in (spec.target_files or []):
                if content:
                    parts.append(f"## Current content of {path} (use MODIFY blocks for this file)")
                    parts.append(f"```\n{content}\n```")
                else:
                    parts.append(f"## {path} (new file — does not exist yet, use FILE block)")
                parts.append("")
            else:
                parts.append(f"## Reference: {path}")
                parts.append(f"```\n{content}\n```")
                parts.append("")

        return "\n".join(parts)

    # ── Main execution ─────────────────────────────────────────────────

    async def execute(
        self,
        spec: BuildSpec,
        file_contents: dict[str, str],
        *,
        timeout: float = 300.0,
    ) -> CopilotBuildResult:
        """Execute a build task using the Copilot SDK.

        The Copilot SDK agent writes files directly to disk (using its own
        Write/Edit tools).  We capture changes via workspace_file_changed
        events and read the resulting files to build file_blocks in the
        native Builder format.

        Args:
            spec: The build specification
            file_contents: Pre-read file contents (target + reference)
            timeout: Max seconds for the session (default 5 min)

        Returns:
            CopilotBuildResult with file blocks in native Builder format
        """
        if not self._started:
            raise RuntimeError("Adapter not started")
        if not self._session_dir_given:
            # BF-896: without an explicit session directory the session would run in
            # the project root with write permission there.
            return CopilotBuildResult(
                success=False,
                error=(
                    "BF-896: no session directory was given; a visiting build session "
                    "runs only in a directory its caller created"
                ),
            )

        try:
            system_message = self._compose_system_message()
            repository_instructions = discover_build_repository_instructions(
                self._instruction_work_dir,
                target_paths=(
                    *(spec.target_files or ()), *(spec.reference_files or ()),
                    *(spec.test_files or ()),
                ),
                global_directory=repository_instruction_directory(
                    getattr(self._runtime, "data_dir", None),
                ),
                policy=instruction_read_policy(self._runtime),
            )
            system_message["content"] = append_repository_instructions(
                system_message["content"], repository_instructions,
            )
            tools = self._build_mcp_tools()
            prompt = self._build_prompt(spec, file_contents)

            session_config: dict[str, Any] = {
                "system_message": system_message,
                "tools": tools,
                "working_directory": self._cwd,
                # BF-896: deny by default; writes and reads only inside the session
                # directory, and only the adapter's own registered tools.
                "on_permission_request": build_session_permission_handler(
                    self._cwd, [getattr(tool, "name", None) for tool in tools],
                ),
            }
            if self._model:
                session_config["model"] = self._model

            session = await self._client.create_session(session_config)

            try:
                # send_and_wait blocks until session is idle or timeout
                await session.send_and_wait({"prompt": prompt}, timeout=timeout)

                # Collect assistant messages
                messages = await session.get_messages()
                collected_output: list[str] = []
                for msg in messages:
                    msg_type = getattr(msg, "type", None)
                    if msg_type == SessionEventType.ASSISTANT_MESSAGE and msg.data.content:
                        collected_output.append(msg.data.content)
            finally:
                await session.disconnect()

            full_output = "".join(collected_output)

            # SDK does NOT emit SESSION_WORKSPACE_FILE_CHANGED events.
            # Primary strategy: scan temp dir for new/changed files.
            file_blocks: list[dict[str, Any]] = []
            cwd = Path(self._cwd)
            changed_paths: list[str] = []
            rejected_count = 0

            # Expected project structure prefixes for file validation
            _EXPECTED_PREFIXES = ("src/", "tests/", "config/", "docs/", "prompts/")

            for f in cwd.rglob("*"):
                try:
                    if not f.is_file() or f.name.startswith("."):
                        continue
                    rel = str(f.relative_to(cwd)).replace("\\", "/")
                    if any(skip in rel for skip in ("__pycache__", ".git/", "node_modules/")):
                        continue
                    # Skip files outside expected project structure
                    if not any(rel.startswith(p) for p in _EXPECTED_PREFIXES):
                        if "/" not in rel:
                            pass  # Root-level file — allow
                        else:
                            logger.warning(
                                "Visiting officer created file outside expected structure: %s — skipping",
                                rel,
                            )
                            rejected_count += 1
                            continue
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if rel not in file_contents or content != file_contents.get(rel, ""):
                        changed_paths.append(rel)
                except (OSError, ValueError):
                    continue

            if rejected_count > 0:
                logger.warning(
                    "Visiting officer: %d file(s) rejected (outside project structure)",
                    rejected_count,
                )

            if changed_paths:
                logger.debug("Visiting builder: found %d changed files on disk: %s", len(changed_paths), changed_paths)

            if changed_paths:
                for rel_path in changed_paths:
                    abs_path = cwd / rel_path
                    if abs_path.is_file():
                        content = abs_path.read_text(encoding="utf-8", errors="replace")
                        original = file_contents.get(rel_path, "")
                        mode = "modify" if original else "create"
                        block: dict[str, Any] = {
                            "path": rel_path,
                            "mode": mode,
                            "content": content,
                            # BF-896: every whole-file block carries the text it was
                            # generated against ("" for an absent or empty file);
                            # execute_approved_build applies it only while the target
                            # still holds exactly that text.
                            "base": original,
                        }
                        file_blocks.append(block)
                        logger.debug("Captured changed file: %s (%s)", rel_path, mode)

            logger.info("Visiting builder: %d messages, %d files captured", len(messages), len(file_blocks))

            # Fallback: if no workspace events, try parsing ===FILE:=== blocks
            if not file_blocks:
                from probos.cognitive.builder import BuilderAgent
                file_blocks = BuilderAgent._parse_file_blocks(full_output)
                for block in file_blocks:
                    if "replacements" not in block:
                        # BF-896: a whole-file block parsed from the text carries the
                        # text it was generated against too ("" for a path the seed does
                        # not name), so execute_approved_build refuses it over a file that
                        # holds anything else instead of overwriting it. A MODIFY block
                        # (it has "replacements") is applied by exact SEARCH text and
                        # stays base-free.
                        block["base"] = file_contents.get(block["path"], "")

            return CopilotBuildResult(
                success=bool(file_blocks),
                file_blocks=file_blocks,
                raw_output=full_output,
            )

        except asyncio.TimeoutError:
            logger.warning("CopilotBuilderAdapter.execute timed out after %.1fs", timeout)
            return CopilotBuildResult(success=False, error=f"Session timed out after {timeout}s")
        except Exception as e:
            logger.warning("CopilotBuilderAdapter.execute failed: %s", e)
            return CopilotBuildResult(success=False, error=str(e))
