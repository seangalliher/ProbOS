"""AD-480a: FederationMCPServer -- inbound MCP server.

Mirror of AD-449 outbound MCPClient on the server side. Reuses JSON-RPC
constants from the AD-449 client. Translates incoming tools/call to
IntentMessage and dispatches via IntentBus.broadcast(federated=False).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING

from probos.events import EventType
from probos.integrations.mcp_bridge.client import (
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.config import FederationMCPServerConfig
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


class FederationMCPServer:
    def __init__(
        self,
        *,
        runtime: "ProbOSRuntime",
        config: "FederationMCPServerConfig",
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._task_store: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._server_task: asyncio.Task | None = None
        self._uvicorn_server: Any | None = None

    @property
    def is_running(self) -> bool:
        return self._server_task is not None and not self._server_task.done()

    async def start(self) -> None:
        if not self._config.enabled:
            return
        try:
            from starlette.applications import Starlette
            from starlette.responses import JSONResponse
            from starlette.routing import Route
            import uvicorn
        except ImportError:
            logger.warning(
                "AD-480a: starlette/uvicorn missing; MCP server disabled"
            )
            return

        async def jsonrpc_endpoint(request):
            body = await request.body()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse(
                    self._error_envelope(None, -32700, "Parse error"),
                    status_code=400,
                )
            session_id = request.headers.get("mcp-session-id", "")
            response = await self.handle_jsonrpc(payload, session_id=session_id)
            headers: dict[str, str] = {}
            assigned = response.pop("_assigned_session", None)
            if assigned:
                headers["Mcp-Session-Id"] = assigned
            return JSONResponse(response, headers=headers)

        app = Starlette(
            routes=[
                Route(
                    self._config.path_prefix or "/mcp",
                    jsonrpc_endpoint,
                    methods=["POST"],
                ),
            ]
        )
        uv_config = uvicorn.Config(
            app,
            host=self._config.bind_host,
            port=self._config.bind_port,
            log_level="warning",
            lifespan="off",
        )
        self._uvicorn_server = uvicorn.Server(uv_config)
        try:
            self._server_task = asyncio.create_task(
                self._uvicorn_server.serve(), name="mcp-server"
            )
        except OSError as exc:
            logger.warning(
                "AD-480a: MCP server bind failed (port %d): %s",
                self._config.bind_port,
                exc,
            )
            self._server_task = None
            self._uvicorn_server = None

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        task = self._server_task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        self._server_task = None
        self._uvicorn_server = None

    # --- JSON-RPC dispatch (test surface) ---

    async def handle_jsonrpc(
        self,
        payload: dict[str, Any],
        *,
        session_id: str = "",
    ) -> dict[str, Any]:
        request_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error_envelope(request_id, -32602, "Invalid params")
        try:
            if method == "initialize":
                return await self._handle_initialize(request_id, params)
            if method == "tools/list":
                return await self._handle_tools_list(request_id)
            if method == "tools/call":
                return await self._handle_tools_call(
                    request_id, params, session_id
                )
            return self._error_envelope(
                request_id, -32601, f"Method not found: {method}"
            )
        except Exception as exc:
            self._emit_failed(method, reason="server_error", detail=str(exc))
            logger.exception("AD-480a: server error handling %s", method)
            return self._error_envelope(
                request_id, -32000, f"Server error: {exc}"
            )

    async def _handle_initialize(
        self, request_id: Any, params: dict
    ) -> dict[str, Any]:
        sid = uuid.uuid4().hex
        self._sessions[sid] = {"created_at": time.time()}
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "probos-mcp-server",
                    "version": "0.1.0",
                },
            },
            "_assigned_session": sid,
        }

    async def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        tools = self._project_tools_from_descriptors()
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {"tools": tools},
        }

    async def _handle_tools_call(
        self,
        request_id: Any,
        params: dict,
        session_id: str,
    ) -> dict[str, Any]:
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._error_envelope(
                request_id, -32602, "arguments must be object"
            )
        if not tool_name:
            return self._error_envelope(request_id, -32602, "name required")

        peer_id = (
            f"mcp-session:{session_id}"
            if session_id
            else f"mcp-anon:{request_id}"
        )
        await self._ensure_peer_registered(peer_id)

        intent = IntentMessage(
            intent=tool_name,
            params=arguments,
            context=f"mcp_server:{peer_id}",
        )
        results = await self._runtime.intent_bus.broadcast(intent, federated=False)
        if not results:
            self._record_outcome(peer_id, False, intent_type=tool_name)
            return self._error_envelope(
                request_id, -32000, "no agent handled tool"
            )
        winning = None
        for r in sorted(results, key=lambda x: x.confidence, reverse=True):
            if r.success:
                winning = r
                break
        if winning is None:
            winning = max(results, key=lambda x: x.confidence)
        self._record_outcome(peer_id, winning.success, intent_type=tool_name)
        self._emit_invoke(method="tools/call", tool=tool_name)
        if not winning.success:
            return self._error_envelope(
                request_id,
                -32000,
                f"tool failed: {winning.error or 'unknown'}",
            )
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(winning.result, default=str),
                    }
                ],
                "isError": False,
            },
        }

    def _project_tools_from_descriptors(self) -> list[dict[str, Any]]:
        try:
            descriptors = list(
                self._runtime.decomposer._intent_descriptors.values()
            )
        except Exception:
            logger.warning(
                "AD-480b: descriptor read failed; returning []", exc_info=True
            )
            return []
        tools: list[dict[str, Any]] = []
        for desc in descriptors:
            params_schema = {
                "type": "object",
                "properties": {
                    pname: {"type": "string", "description": pdesc}
                    for pname, pdesc in desc.params.items()
                },
                "required": list(desc.params.keys()),
            }
            tools.append(
                {
                    "name": desc.name,
                    "description": desc.description,
                    "inputSchema": params_schema,
                }
            )
        return tools

    async def _ensure_peer_registered(self, peer_id: str) -> None:
        from probos.federation.peer import FederationPeer

        await self._runtime.federation_peer_registry.register_peer(
            FederationPeer(
                protocol="mcp",
                peer_id=peer_id,
                endpoint=peer_id,
                trust_record_id=f"mcp-peer:{peer_id}",
            )
        )

    def _record_outcome(
        self, peer_id: str, success: bool, *, intent_type: str = ""
    ) -> None:
        self._runtime.federation_peer_registry.record_outcome(
            peer_id, success, intent_type=intent_type
        )

    def _emit_invoke(self, *, method: str, tool: str) -> None:
        try:
            self._runtime.emit_event(
                EventType.MCP_BRIDGE_INVOKE,
                {"side": "server", "method": method, "tool": tool},
            )
        except Exception:
            logger.warning(
                "AD-480a: MCP_BRIDGE_INVOKE emit failed", exc_info=True
            )

    def _emit_failed(
        self, method: str, *, reason: str, detail: str = ""
    ) -> None:
        try:
            self._runtime.emit_event(
                EventType.MCP_BRIDGE_FAILED,
                {
                    "side": "server",
                    "method": method,
                    "reason": reason,
                    "detail": detail[:200],
                },
            )
        except Exception:
            logger.warning(
                "AD-480a: MCP_BRIDGE_FAILED emit failed", exc_info=True
            )

    @staticmethod
    def _error_envelope(
        request_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }
