"""AD-480a: FederationMCPServer -- inbound MCP server.

Mirror of AD-449 outbound MCPClient on the server side. Reuses JSON-RPC
constants from the AD-449 client. Translates incoming tools/call to
IntentMessage and dispatches via IntentBus.broadcast(federated=False).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Iterable
from typing import Any, TYPE_CHECKING

from probos.events import EventType
from probos.integrations.mcp_bridge.client import (
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
)
from probos.types import IntentDescriptor, IntentMessage

if TYPE_CHECKING:
    from probos.config import FederationMCPServerConfig
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

_UNAVAILABLE = (
    "Tool {name!r} is not available over MCP (BF-875): an authenticated caller may run only "
    "an intent named in federation.mcp_server.exposed_intents that does not require consensus"
)
_NOT_AN_OBJECT = "Invalid Request: the body must be a JSON-RPC request object"
_NOT_JSON_RPC_2_0 = 'Invalid Request: a JSON-RPC 2.0 request carries "jsonrpc": "2.0" and a string method'
MAX_REQUEST_BYTES = 1_048_576  # BF-875: one JSON-RPC request; cost: a larger request is refused with 413 (the HXI games send a few hundred bytes)
_TOO_LARGE = f"Invalid Request: the request body exceeds {MAX_REQUEST_BYTES} bytes"


def bearer_token_matches(authorization: str, expected: str) -> bool:
    """BF-875: whether ``authorization`` is ``Bearer <expected>``, compared in constant time.

    An empty ``expected`` matches nothing, so an unset token authenticates no one.
    """
    scheme, _, presented = authorization.strip().partition(" ")
    if not expected or scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(presented.strip().encode("utf-8"), expected.encode("utf-8"))


def is_json_media_type(content_type: str) -> bool:
    """BF-875: whether a Content-Type header value names ``application/json``."""
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def exposable_intents(
    collect: Callable[[], Iterable[IntentDescriptor]] | None,
    exposed: Collection[str],
) -> dict[str, IntentDescriptor]:
    """BF-875: what an inbound server may dispatch: listed, declared, never consensus-flagged (BF-876: A2A too)."""
    if collect is None or not exposed:
        return {}
    try:
        declared = list(collect())
    except Exception:
        logger.warning(
            "BF-875: reading the intent descriptors failed; the inbound MCP or A2A server "
            "exposes no intents until a read succeeds",
            exc_info=True,
        )
        return {}
    listed = set(exposed)
    flagged = {d.name for d in declared if d.requires_consensus}
    return {d.name: d for d in declared if d.name in listed and d.name not in flagged}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _refuse_non_finite(token: str) -> float:
    """BF-875: NaN and +/-Infinity are not JSON; refusing them keeps every reply serialisable."""
    raise ValueError("NaN and Infinity are not JSON numbers")


def _finite_float(text: str) -> float:
    """BF-875: a JSON number that overflows a float is refused, never carried as infinity."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("a JSON number overflowed to infinity")
    return value


def _is_jsonrpc_id(value: Any) -> bool:
    """BF-875: JSON-RPC 2.0 -- an id is a string, a (non-boolean) number, or null."""
    return value is None or isinstance(value, str) or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _encodes_as_utf8(payload: dict[str, Any]) -> bool:
    """BF-875: True when the parsed request re-serialises to UTF-8 (no lone surrogate anywhere)."""
    try:
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (UnicodeEncodeError, RecursionError, ValueError):
        return False
    return True


def strict_json_loads(data: str | bytes) -> Any:
    """BF-876: ``json.loads`` under BF-875's number rules, for every JSON an inbound server parses.

    Malformed JSON or bytes, NaN, Infinity, a float overflow and an integer past Python's digit
    limit raise ``ValueError``; nesting past the recursion budget raises ``RecursionError``.
    """
    return json.loads(data, parse_constant=_refuse_non_finite, parse_float=_finite_float)


def parse_jsonrpc_request(body: bytes) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """BF-875: ``(request, None)``, or ``(None, error)`` for a door to return with HTTP 400.

    A malformed body is the caller's error, never a 500. A batch (a JSON array) is
    refused as -32600 rather than half-supported, and
    a number JSON cannot hold (too many digits, NaN, Infinity) is a parse error.
    BF-876: an object without ``"jsonrpc": "2.0"`` and a string ``method`` is -32600.
    """
    try:
        payload = strict_json_loads(body)
    except (ValueError, RecursionError):  # BF-875: bad JSON, bad UTF-8, a huge or non-finite number, deep nesting
        return None, _jsonrpc_error(None, -32700, "Parse error")
    if not isinstance(payload, dict):
        return None, _jsonrpc_error(None, -32600, _NOT_AN_OBJECT)
    if payload.get("jsonrpc") != JSONRPC_VERSION or not isinstance(payload.get("method"), str):  # BF-876: the HXI bridge forwards nothing else
        return None, _jsonrpc_error(None, -32600, _NOT_JSON_RPC_2_0)
    if "id" in payload and not _is_jsonrpc_id(payload["id"]):  # BF-875: JSON-RPC 2.0 ids are a string, a number or null
        return None, _jsonrpc_error(
            None, -32600, "Invalid Request: id must be a string, a number or null"
        )
    if not _encodes_as_utf8(payload):  # BF-875: a reply that echoes a lone surrogate cannot be sent
        return None, _jsonrpc_error(
            None, -32600, "Invalid Request: the request holds text that cannot be encoded as UTF-8"
        )
    return payload, None


async def read_bounded_body(request: Any, limit: int = MAX_REQUEST_BYTES) -> bytes | None:
    """BF-875: the request body, or None as soon as it exceeds ``limit`` bytes -- it is never buffered past that."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:  # BF-875: stop reading, never buffer an oversized body
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def build_mcp_app(
    *,
    path: str,
    auth_token: str,
    handle_jsonrpc: Callable[..., Awaitable[dict[str, Any]]],
) -> Any:
    """BF-875: the Starlette app ``start()`` serves, as a function so tests need no socket.

    The bearer token is checked first, so an unauthenticated caller learns nothing
    about the body it sent. The JSON content type is checked second: a browser
    cannot send it cross-origin without a CORS preflight.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def jsonrpc_endpoint(request):
        auth_header = request.headers.get("authorization", "")
        if not bearer_token_matches(auth_header, auth_token):
            logger.info(
                "BF-875: refused an MCP request from %s: missing or wrong bearer token",
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                _jsonrpc_error(None, -32600, "Invalid Request: authentication failed"),
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not is_json_media_type(request.headers.get("content-type", "")):
            return JSONResponse(
                _jsonrpc_error(
                    None, -32600, "Invalid Request: Content-Type must be application/json"
                ),
                status_code=415,
            )
        body = await read_bounded_body(request)
        if body is None:  # BF-875: Door A refuses an oversized body
            return JSONResponse(_jsonrpc_error(None, -32600, _TOO_LARGE), status_code=413)
        payload, error = parse_jsonrpc_request(body)
        if error is not None:
            return JSONResponse(error, status_code=400)
        session_id = request.headers.get("mcp-session-id", "")
        response = await handle_jsonrpc(
            payload, session_id=session_id, auth_header=auth_header
        )
        headers: dict[str, str] = {}
        assigned = response.pop("_assigned_session", None)
        if assigned:
            headers["Mcp-Session-Id"] = assigned
        return JSONResponse(response, headers=headers)

    return Starlette(
        routes=[
            Route(
                path or "/mcp",
                jsonrpc_endpoint,
                methods=["POST"],
            ),
        ]
    )


class FederationMCPServer:
    def __init__(
        self,
        *,
        runtime: "ProbOSRuntime",
        config: "FederationMCPServerConfig",
        collect_intent_descriptors_fn: Callable[[], Iterable[IntentDescriptor]] | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._collect_intent_descriptors_fn = collect_intent_descriptors_fn
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
            import uvicorn
            app = build_mcp_app(
                path=self._config.path_prefix,
                auth_token=self._config.auth_token,
                handle_jsonrpc=self.handle_jsonrpc,
            )
        except ImportError:
            logger.warning(
                "AD-480a: starlette/uvicorn missing; MCP server disabled"
            )
            return
        listed = self._config.exposed_intents
        unexposed = sorted(
            set(listed) - set(exposable_intents(self._collect_intent_descriptors_fn, listed))
        )
        if unexposed:
            logger.warning(
                "BF-875: federation.mcp_server.exposed_intents names %s, which no agent "
                "declares or which require consensus; the MCP server refuses them while "
                "that holds",
                ", ".join(unexposed),
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
        auth_header: str = "",
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._error_envelope(None, -32600, _NOT_AN_OBJECT)
        request_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error_envelope(request_id, -32602, "Invalid params")
        # BF-875: intents need the bearer token; the HXI bridge passes none, so app tools only.
        authenticated = bearer_token_matches(auth_header, self._config.auth_token)
        try:
            if method == "initialize":
                return await self._handle_initialize(request_id, params)
            if method == "tools/list":
                return await self._handle_tools_list(request_id, authenticated)
            if method == "tools/call":
                return await self._handle_tools_call(
                    request_id, params, session_id, authenticated
                )
            if method == "resources/read":
                return await self._handle_resources_read(request_id, params)
            return self._error_envelope(
                request_id, -32601, f"Method not found: {str(method)[:80]}"
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

    async def _handle_tools_list(
        self, request_id: Any, authenticated: bool
    ) -> dict[str, Any]:
        tools = self._project_tools_from_descriptors() if authenticated else []
        # AD-597b: merge app-registry tools. BF-875: internal ones only, as tools/call serves.
        registry = getattr(self._runtime, "mcp_app_registry", None)
        if registry is not None:
            tools.extend(registry.list_tools(include_external=False))
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {"tools": tools},
        }

    async def _handle_resources_read(
        self, request_id: Any, params: dict
    ) -> dict[str, Any]:
        # AD-597a: ui:// resource lookup via runtime.mcp_app_registry
        uri = params.get("uri", "")
        if not isinstance(uri, str) or not uri:  # BF-875: a uri is a non-empty string
            return self._error_envelope(request_id, -32602, "uri required")
        registry = getattr(self._runtime, "mcp_app_registry", None)
        if registry is None:
            return self._error_envelope(
                request_id, -32000, "mcp_app_registry not available"
            )
        result = await registry.read_resource(uri)
        if result is None:
            return self._error_envelope(
                request_id, -32000, f"resource not found: {uri[:80]}"
            )
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    async def _handle_tools_call(
        self,
        request_id: Any,
        params: dict,
        session_id: str,
        authenticated: bool,
    ) -> dict[str, Any]:
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._error_envelope(
                request_id, -32602, "arguments must be object"
            )
        if not isinstance(tool_name, str) or not tool_name:  # BF-875: a name is a non-empty string
            return self._error_envelope(request_id, -32602, "name required")

        peer_id = (
            f"mcp-session:{session_id}"
            if session_id
            else f"mcp-anon:{request_id}"
        )

        # AD-597b: app-registry tools take precedence over intent dispatch.
        # App tools use hyphenated names (game-move, game-state) which never
        # collide with IntentDescriptor.name (system_status, file_read, ...).
        # BF-875: internal ones only; an external tool proxies its server past mcp_invoke's gates.
        registry = getattr(self._runtime, "mcp_app_registry", None)
        if registry is not None and registry.has_tool(tool_name, include_external=False):
            await self._ensure_peer_registered(peer_id)
            try:
                app_result = await registry.call_tool(tool_name, arguments, include_external=False)
            except Exception as exc:
                self._record_outcome(peer_id, False, intent_type=tool_name)
                return self._error_envelope(
                    request_id, -32000, f"app tool failed: {exc}"
                )
            self._record_outcome(
                peer_id,
                not app_result.get("isError", False),
                intent_type=tool_name,
            )
            self._emit_invoke(method="tools/call", tool=tool_name)
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": app_result,
            }

        exposed = (
            exposable_intents(
                self._collect_intent_descriptors_fn, self._config.exposed_intents
            )
            if authenticated
            else {}
        )
        if tool_name not in exposed:
            logger.info(
                "BF-875: refused MCP tools/call %r from %r (authenticated=%s)",
                str(tool_name)[:80], peer_id[:80], authenticated,
            )
            self._emit_failed("tools/call", reason="not_exposed", detail=str(tool_name))
            return self._error_envelope(
                request_id, -32602, _UNAVAILABLE.format(name=str(tool_name)[:80])
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
        tools: list[dict[str, Any]] = []
        for desc in exposable_intents(
            self._collect_intent_descriptors_fn, self._config.exposed_intents
        ).values():
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
        return _jsonrpc_error(request_id, code, message)
