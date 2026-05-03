"""MCP Bridge -- ProbOS-as-MCP-client (AD-449).

v1 ships the OSS bridge infrastructure: JSON-RPC 2.0 over Streamable HTTP,
session management, tool routing into the existing ToolRegistry, and
EgressPolicy-gated outbound dispatch.
"""

from probos.integrations.mcp_bridge.adapter import MCPToolAdapter
from probos.integrations.mcp_bridge.bridge import MCPBridge
from probos.integrations.mcp_bridge.client import MCPClient, MCPProtocolError
from probos.integrations.mcp_bridge.session import MCPSession

__all__ = [
    "MCPBridge",
    "MCPClient",
    "MCPProtocolError",
    "MCPSession",
    "MCPToolAdapter",
]
