"""AD-423a: Tool protocol and core types.

Defines the uniform interface for all tool types in ProbOS.
Absorbs AD-483 (Tool Layer — Instruments) programming model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ToolType(str, Enum):
    """Nine-category tool taxonomy (AD-422)."""

    UTILITY_AGENT = "utility_agent"
    INFRA_SERVICE = "infra_service"
    MCP_SERVER = "mcp_server"
    REMOTE_API = "remote_api"
    COMPUTER_USE = "computer_use"
    BROWSER = "browser"
    COMMUNICATION = "communication"
    FEDERATION = "federation"
    DETERMINISTIC_FUNCTION = "deterministic_function"


class ToolPermission(str, Enum):
    """Additive CRUD+O permission levels (AD-423b).

    Each level includes the powers of all lower levels.
    NONE < OBSERVE < READ < WRITE < FULL.
    """

    NONE = "none"          # No access
    OBSERVE = "observe"    # Passive monitoring only
    READ = "read"          # Query/retrieve, no mutations
    WRITE = "write"        # Create, modify (includes read)
    FULL = "full"          # Delete, destructive ops (includes write)


# Numeric ordering for comparison
_PERMISSION_ORDER: dict[ToolPermission, int] = {
    ToolPermission.NONE: 0,
    ToolPermission.OBSERVE: 1,
    ToolPermission.READ: 2,
    ToolPermission.WRITE: 3,
    ToolPermission.FULL: 4,
}


def permission_includes(held: ToolPermission, required: ToolPermission) -> bool:
    """Does `held` permission include `required`?

    Additive: WRITE includes READ includes OBSERVE.
    """
    return _PERMISSION_ORDER[held] >= _PERMISSION_ORDER[required]


class ToolConcurrency(str, Enum):
    """Tool concurrency mode (AD-423b LOTO)."""

    CONCURRENT = "concurrent"  # Multiple agents can use simultaneously
    EXCLUSIVE = "exclusive"    # Only one agent at a time (LOTO)


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation."""

    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None


@runtime_checkable
class Tool(Protocol):
    """Uniform interface for all ProbOS tools.

    A Tool is any callable instrument an agent can invoke —
    a Ship's Computer service, an infrastructure agent, an MCP server,
    a deterministic function, etc.

    Implementations satisfy this protocol; no inheritance required
    (Interface Segregation Principle).
    """

    @property
    def tool_id(self) -> str:
        """Unique identifier (e.g., 'codebase_query', 'ward_room_post')."""
        ...

    @property
    def name(self) -> str:
        """Human-readable display name."""
        ...

    @property
    def tool_type(self) -> ToolType:
        """Category from the AD-422 taxonomy."""
        ...

    @property
    def description(self) -> str:
        """What this tool does — shown in discovery results."""
        ...

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema describing accepted parameters."""
        ...

    @property
    def output_schema(self) -> dict[str, Any]:
        """JSON Schema describing the result structure."""
        ...

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        """Execute the tool with the given parameters.

        Args:
            params: Input parameters matching input_schema.
            context: Invocation context dict. When called through ToolContext
                     (AD-423c), includes agent_id, permission, agent_department,
                     and agent_rank. Direct callers may pass any dict.

        Returns:
            ToolResult with output or error.
        """
        ...


@dataclass
class ToolRegistration:
    """Metadata record for a registered tool.

    Wraps a Tool instance with registration metadata used by the
    ToolRegistry for lookup, filtering, and lifecycle management.
    """

    tool: Tool
    domain: str = "*"  # "security", "engineering", "medical", "*" (universal)
    department: str | None = None  # Restricts to a department (None = ship-wide)
    tags: list[str] = field(default_factory=list)  # Capability tags for discovery
    provider: str = ""  # "ship_computer", "ward_room", "dreaming_engine", etc.
    enabled: bool = True
    registered_at: float = field(default_factory=time.time)

    # AD-423b: Permission & scoping fields
    default_permissions: dict[str, str] = field(default_factory=dict)
    # Maps Rank value → ToolPermission value, e.g.:
    # {"ensign": "read", "lieutenant": "write", "commander": "write", "senior_officer": "full"}
    # Empty dict = ship-wide default (READ for all ranks)

    restricted_to: list[str] | None = None
    # If set, only these agent IDs/types can access (within scope)

    concurrency: str = "concurrent"  # "concurrent" | "exclusive"
    lock_timeout_seconds: float | None = None  # Auto-release for exclusive tools

    @property
    def tool_id(self) -> str:
        return self.tool.tool_id

    @property
    def tool_type(self) -> ToolType:
        return self.tool.tool_type

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "tool_id": self.tool.tool_id,
            "name": self.tool.name,
            "tool_type": self.tool.tool_type.value,
            "description": self.tool.description,
            "domain": self.domain,
            "department": self.department,
            "tags": self.tags,
            "provider": self.provider,
            "enabled": self.enabled,
            "input_schema": self.tool.input_schema,
            "output_schema": self.tool.output_schema,
            "default_permissions": self.default_permissions,
            "restricted_to": self.restricted_to,
            "concurrency": self.concurrency,
            "lock_timeout_seconds": self.lock_timeout_seconds,
        }


@dataclass
class ToolPreference:
    """Priority-ranked tool selection for a skill.

    Links SkillDefinition → Tool with priority ordering.
    When a skill needs a tool, preferences are tried in priority order
    (lower number = higher priority). Fallback cascade is AD-423c scope.
    """

    tool_id: str
    priority: int = 0  # Lower = higher priority
    context: str = ""  # When to prefer this tool (e.g., "when offline", "for large files")


@dataclass(frozen=True)
class ToolAccessGrant:
    """Captain-issued per-agent tool permission override (AD-423b).

    Grants elevate access above the default_permissions matrix.
    Restrictions lower access below the default. Both survive restart
    (SQLite-backed via ToolPermissionStore).
    """

    id: str
    agent_id: str           # Target — sovereign_id or agent slot ID
    tool_id: str
    permission: ToolPermission
    is_restriction: bool = False   # True = restrict down, False = grant up
    reason: str = ""
    issued_by: str = "captain"
    issued_at: float = 0.0
    expires_at: float | None = None  # None = until revoked
    revoked: bool = False
    revoked_at: float | None = None
