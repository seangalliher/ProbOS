"""AD-449: MCPSession -- opaque session handle for an MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MCPSession:
    """One MCP server session.

    server_url is the canonical Streamable HTTP endpoint (e.g.,
    https://example.com/mcp). session_id is server-assigned during
    initialize() and threaded back via the Mcp-Session-Id header per
    the Streamable HTTP specification.
    capabilities is the server's reported capability set from the
    initialize response (cached for the session lifetime).
    """

    server_url: str
    session_id: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, dict] = field(default_factory=dict)
