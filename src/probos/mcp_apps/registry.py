"""AD-597a: MCP App registry — internal + external app tool/resource catalog."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)

# Strict ui:// path validation (dispatch gate_1 #4)
_UI_PATH_RE = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_.-]+)*$")
# CSP header validation (dispatch gate_1 #5)
_CSP_RE = re.compile(r"^[a-zA-Z0-9 ;:'\"_/-]+$")

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class AppToolRegistration:
    name: str
    description: str
    input_schema: dict[str, Any]
    ui_resource_uri: str
    csp: str
    handler: ToolHandler
    external: bool = False
    server_id: str = ""


@dataclass(frozen=True)
class AppResourceRegistration:
    uri: str
    mime_type: str
    content: bytes
    csp: str = ""


class MCPAppRegistry:
    """In-memory registry of MCP App tools and ui:// resources."""

    def __init__(
        self,
        *,
        internal_default_csp: str,
        external_default_csp: str,
    ) -> None:
        if not _CSP_RE.match(internal_default_csp):
            raise ValueError("AD-597a: invalid internal_default_csp")
        if not _CSP_RE.match(external_default_csp):
            raise ValueError("AD-597a: invalid external_default_csp")
        self._tools: dict[str, AppToolRegistration] = {}
        self._resources: dict[str, AppResourceRegistration] = {}
        self._external_clients: dict[str, Any] = {}  # server_id -> MCPClient
        self._internal_default_csp = internal_default_csp
        self._external_default_csp = external_default_csp
        self._emit_event_fn: Callable[..., None] | None = None

    def set_event_callback(self, emit_fn: Callable[..., None]) -> None:
        self._emit_event_fn = emit_fn

    # --- Tool registration ---

    def register_app_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        ui_resource_uri: str,
        handler: ToolHandler,
        csp: str = "",
    ) -> None:
        if not name:
            raise ValueError("AD-597a: tool name required")
        if csp and not _CSP_RE.match(csp):
            raise ValueError(f"AD-597a: invalid CSP for tool {name}")
        if name in self._tools:
            logger.warning("AD-597a: replacing app tool %s", name)
        reg = AppToolRegistration(
            name=name,
            description=description,
            input_schema=input_schema,
            ui_resource_uri=ui_resource_uri,
            csp=csp or self._internal_default_csp,
            handler=handler,
            external=False,
        )
        self._tools[name] = reg
        self._emit(EventType.MCP_APP_TOOL_REGISTERED, {"name": name, "external": False})

    def register_external_app(
        self,
        *,
        server_id: str,
        tool_dict: dict[str, Any],
        csp: str,
        mcp_client: Any,
    ) -> None:
        if not server_id:
            raise ValueError("AD-597a: server_id required")
        if csp and not _CSP_RE.match(csp):
            raise ValueError(f"AD-597a: invalid external CSP for server {server_id}")
        name = tool_dict.get("name", "")
        if not name:
            raise ValueError("AD-597a: external tool missing name")
        ui_uri = (
            tool_dict.get("_meta", {})
            .get("ui", {})
            .get("resourceUri", "")
        )

        async def _external_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await mcp_client.call_tool(name, args)

        reg = AppToolRegistration(
            name=name,
            description=tool_dict.get("description", ""),
            input_schema=tool_dict.get("inputSchema", {}),
            ui_resource_uri=ui_uri,
            csp=csp or self._external_default_csp,
            handler=_external_handler,
            external=True,
            server_id=server_id,
        )
        self._tools[name] = reg
        self._external_clients[server_id] = mcp_client
        self._emit(
            EventType.MCP_APP_EXTERNAL_DISCOVERED,
            {"server_id": server_id, "name": name},
        )

    def unregister_app(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for reg in self._tools.values():
            entry = {
                "name": reg.name,
                "description": reg.description,
                "inputSchema": reg.input_schema,
                "_meta": {
                    "ui": {
                        "resourceUri": reg.ui_resource_uri,
                        "csp": reg.csp,
                    },
                    "probos": {
                        "external": reg.external,
                        "server_id": reg.server_id,
                    },
                },
            }
            out.append(entry)
        return out

    # --- Resource registration ---

    def register_app_resource(
        self,
        *,
        uri: str,
        mime_type: str,
        content: bytes,
        csp: str = "",
    ) -> None:
        path = self._extract_ui_path(uri)
        if path is None or not _UI_PATH_RE.match(path):
            raise ValueError(f"AD-597a: invalid ui:// uri {uri!r}")
        # Reject path-traversal segments (gate_1 #4).
        if ".." in path.split("/"):
            raise ValueError(f"AD-597a: path-traversal in ui:// uri {uri!r}")
        if csp and not _CSP_RE.match(csp):
            raise ValueError(f"AD-597a: invalid CSP for resource {uri}")
        self._resources[uri] = AppResourceRegistration(
            uri=uri,
            mime_type=mime_type,
            content=content,
            csp=csp or self._internal_default_csp,
        )

    async def read_resource(self, uri: str) -> dict[str, Any] | None:
        # Internal: in-memory lookup.
        reg = self._resources.get(uri)
        if reg is not None:
            self._emit(EventType.MCP_APP_RESOURCE_READ, {"uri": uri, "external": False})
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": reg.mime_type,
                        "blob": None,
                        "text": reg.content.decode("utf-8", errors="replace"),
                    }
                ],
                "_meta": {"ui": {"csp": reg.csp}},
            }
        # External: ui://external/<server_id>/<inner_uri> — route via MCPClient.read_resource.
        if uri.startswith("ui://external/"):
            remainder = uri[len("ui://external/"):]
            server_id, _sep, _rest = remainder.partition("/")
            client = self._external_clients.get(server_id)
            if client is None:
                return None
            inner = uri
            for reg_tool in self._tools.values():
                if (
                    reg_tool.external
                    and reg_tool.server_id == server_id
                    and reg_tool.ui_resource_uri == uri
                ):
                    inner = reg_tool.ui_resource_uri
                    break
            try:
                external_result = await client.read_resource(inner)
            except Exception as exc:
                logger.warning(
                    "AD-597f: external read_resource failed for %s: %s", uri, exc,
                )
                return None
            self._emit(EventType.MCP_APP_RESOURCE_READ, {"uri": uri, "external": True})
            return external_result
        return None

    def get_resource_csp(self, uri: str) -> str:
        reg = self._resources.get(uri)
        return reg.csp if reg else ""

    def get_resource_mime(self, uri: str) -> str:
        reg = self._resources.get(uri)
        return reg.mime_type if reg else ""

    # --- Tool invocation ---

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        reg = self._tools.get(name)
        if reg is None:
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"unknown app tool: {name}"}
                ],
            }
        try:
            result = await reg.handler(arguments)
            self._emit(EventType.MCP_APP_TOOL_INVOKED, {"name": name})
            return result
        except Exception as exc:
            logger.warning(
                "AD-597a: app tool %s handler failed: %s", name, exc
            )
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"tool {name} failed: {exc}"}
                ],
            }

    # --- Helpers ---

    @staticmethod
    def _extract_ui_path(uri: str) -> str | None:
        if not uri.startswith("ui://"):
            return None
        return uri[len("ui://"):]

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, payload)
        except Exception:
            logger.warning("AD-597a: event emit failed", exc_info=True)
