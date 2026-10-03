"""AD-480d: FederationA2AServer -- inbound A2A server.

ProbOS-as-A2A-server. Hosts /.well-known/agent.json and JSON-RPC tasks/send
+ tasks/get synchronously. Streaming (tasks/sendSubscribe) and push
(tasks/pushNotification/*) parked at AD-480j / AD-480m.

BF-876: every JSON-RPC request needs ``Authorization: Bearer <federation.a2a.auth_token>``;
an ``outbound_peers`` token is what this ship presents to a peer and never authenticates
a caller. ``tasks/send`` dispatches only an intent that ``federation.a2a.exposed_intents``
lists, an agent declares, and no declaration flags ``requires_consensus``; the agent card
advertises exactly that set and the bearer requirement. The door and its helpers are
BF-875's, shared with the MCP server.

AD-1198 slice 3b: while ``federation.peer_admission_enabled`` is armed, a request without an
``Authorization`` header is a signed peer request -- an AD-1197 envelope that a pinned peer
sealed for this ship (topic ``a2a_request``), whose payload is the JSON-RPC request -- and
``probos.federation.peer_requests`` authenticates it. Its caller is the node that signed it,
never a header. The bearer stays the door for A2A clients that are not ProbOS ships, and every
bearer holder is then one caller. Each caller has its own trust record (``a2a-node:<node id>``
or ``a2a-bearer``: names no unarmed label can produce) and reads only the tasks it created.
Unarmed, nothing here changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TYPE_CHECKING, cast

from probos.federation.mcp_server import (
    MAX_REQUEST_BYTES,
    bearer_token_matches,
    exposable_intents,
    is_json_media_type,
    parse_jsonrpc_request,
    read_bounded_body,
    strict_json_loads,
)
from probos.federation.peer_requests import A2A_REQUEST, max_peer_request_bytes
from probos.types import IntentDescriptor, IntentMessage

if TYPE_CHECKING:
    from probos.config import FederationA2AConfig
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


JSONRPC_VERSION = "2.0"

_TASK_STORE_MAX = 1000
_AUTH_FAILED = "Invalid Request: authentication failed"
_NOT_AN_OBJECT = "Invalid Request: the body must be a JSON-RPC request object"
_TOO_LARGE = f"Invalid Request: the request body exceeds {MAX_REQUEST_BYTES} bytes"
_UNAVAILABLE = (
    "Skill {name!r} is not available over A2A (BF-876): an authenticated caller may run only "
    "an intent named in federation.a2a.exposed_intents that does not require consensus"
)
_BAD_PARTS = "Invalid params: message.parts must be an array"
_BAD_ARGUMENTS = "Invalid params: the arguments after the skill id must be one JSON object"
_BEARER_CALLER = "a2a-bearer"  # AD-1198 slice 3b: every bearer holder, while peer admission is armed
_NODE_CALLER = "a2a-node:"  # AD-1198 slice 3b: a pinned peer's caller name is this plus its node id


class PeerRequestAuthenticator(Protocol):
    """What the A2A server needs to authenticate a signed peer request; ``PeerRequests`` satisfies it (AD-1198)."""

    async def authenticate_payload(self, body: bytes, *, topic: str) -> tuple[str, dict[str, Any]] | None: ...


@dataclass(frozen=True)
class _Caller:
    """Whom a dispatched request is for: its peer-registry entry, its trust record and its task namespace."""

    peer_id: str
    trust_record_id: str
    owner: str


def _labelled(peer_id: str) -> _Caller:
    """BF-876's caller: a label it chose names its trust record, and every bearer holder shares one task namespace."""
    return _Caller(peer_id, f"a2a-peer:{peer_id}", "")


def _principal(name: str) -> _Caller:
    """AD-1198 slice 3b: an armed caller, whose registry entry, trust record and task namespace are all ``name``."""
    return _Caller(name, name, name)  # AD-1198 armed: one name for the registry entry, the trust record and the tasks


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def build_a2a_app(
    *,
    agent_card_path: str,
    auth_token: str,
    handle_agent_card_request: Callable[[], Awaitable[dict[str, Any]]],
    handle_jsonrpc: Callable[..., Awaitable[dict[str, Any]]],
    handle_peer_request: Callable[[bytes], Awaitable[tuple[int, dict[str, Any]] | None]] | None = None,
) -> Any:
    """BF-876: the Starlette app ``start()`` serves, as a function so tests need no socket.

    The agent card stays public. ``POST /a2a`` checks the bearer token first, so an
    unauthenticated caller learns nothing about the body it sent; then the JSON content
    type, which a browser cannot send cross-origin without a CORS preflight; then the
    size; then the JSON-RPC shape -- BF-875's order and helpers.

    AD-1198 slice 3b: given ``handle_peer_request`` (peer admission armed), a request with no
    ``Authorization`` header is a signed peer request instead. Its body is read up to the A2A
    peer-request bound and handed over whole, and a refusal is exactly the 401 a request with
    no bearer token gets. A request with the header takes the bearer door, unchanged.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def unauthenticated():
        return JSONResponse(
            _jsonrpc_error(None, -32600, _AUTH_FAILED),
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def agent_card_endpoint(request):
        return JSONResponse(await handle_agent_card_request())

    async def jsonrpc_endpoint(request):
        auth_header = request.headers.get("authorization", "")
        if handle_peer_request is not None and "authorization" not in request.headers:  # AD-1198 armed: no bearer, so a signed peer request
            body = await read_bounded_body(request, max_peer_request_bytes(A2A_REQUEST))  # AD-1198 the A2A peer-request bound
            answered = None if body is None else await handle_peer_request(body)
            if answered is None:  # AD-1198 every refused peer request is the unauthenticated 401
                return unauthenticated()
            status, response = answered
            return JSONResponse(response, status_code=status)
        if not bearer_token_matches(auth_header, auth_token):
            logger.info(
                "BF-876: refused an A2A request from %s: missing or wrong bearer token",
                request.client.host if request.client else "unknown",
            )
            return unauthenticated()
        if not is_json_media_type(request.headers.get("content-type", "")):
            return JSONResponse(
                _jsonrpc_error(
                    None, -32600, "Invalid Request: Content-Type must be application/json"
                ),
                status_code=415,
            )
        body = await read_bounded_body(request)
        if body is None:  # BF-876: an oversized body is refused before it is buffered
            return JSONResponse(_jsonrpc_error(None, -32600, _TOO_LARGE), status_code=413)
        payload, error = parse_jsonrpc_request(body)
        if error is not None:
            return JSONResponse(error, status_code=400)
        # BF-876: the peer header only labels the trust record; it never authenticates.
        peer_id = request.headers.get("x-a2a-peer-id", "") or (
            request.client.host if request.client else ""
        )
        response = await handle_jsonrpc(
            payload, peer_id=peer_id, auth_header=auth_header
        )
        return JSONResponse(response)

    return Starlette(
        routes=[
            Route(
                agent_card_path or "/.well-known/agent.json",
                agent_card_endpoint,
                methods=["GET"],
            ),
            Route("/a2a", jsonrpc_endpoint, methods=["POST"]),
        ]
    )


class FederationA2AServer:
    def __init__(
        self,
        *,
        runtime: "ProbOSRuntime",
        config: "FederationA2AConfig",
        collect_intent_descriptors_fn: Callable[[], Iterable[IntentDescriptor]] | None = None,
        peer_admission_enabled: bool = False,
        peer_requests: PeerRequestAuthenticator | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._collect_intent_descriptors_fn = collect_intent_descriptors_fn
        self._armed = peer_admission_enabled is True  # AD-1198 armed: callers are principals, never labels
        self._peer_requests = peer_requests if self._armed else None  # AD-1198 signed requests only while armed
        self._task_store: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()
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
            app = build_a2a_app(
                agent_card_path=self._config.agent_card_path,
                auth_token=self._config.auth_token,
                handle_agent_card_request=self.handle_agent_card_request,
                handle_jsonrpc=self.handle_jsonrpc,
                handle_peer_request=self.handle_peer_request if self._armed else None,  # AD-1198 the signed door exists only while armed
            )
        except ImportError:
            logger.warning(
                "AD-480d: starlette/uvicorn missing; A2A server disabled"
            )
            return
        if self._armed and self._peer_requests is None:  # AD-1198 armed without the federation seam
            logger.warning(
                "AD-1198: peer admission is armed but federation peer requests are unavailable (federation is not "
                "running), so the A2A server refuses every signed request; bearer requests are served as one caller",
            )
        listed = self._config.exposed_intents
        unexposed = sorted(set(listed) - set(self._exposable()))
        if unexposed:
            logger.warning(
                "BF-876: federation.a2a.exposed_intents names %s, which no agent declares "
                "or which require consensus; the A2A server refuses them while that holds",
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
                self._uvicorn_server.serve(), name="a2a-server"
            )
        except OSError as exc:
            logger.warning(
                "AD-480d: A2A server bind failed (port %d): %s",
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

    # --- Test surface (no ASGI loop required) ---

    async def handle_agent_card_request(self) -> dict[str, Any]:
        from probos.federation.a2a.agent_card import AgentCard

        base_url = f"http://{self._config.bind_host}:{self._config.bind_port}"
        try:
            from probos import __version__
        except ImportError:
            __version__ = "0.1.0"
        # BF-876: the card lists exactly what tasks/send would dispatch.
        card = AgentCard.from_runtime(
            self._runtime,
            base_url=base_url,
            version=__version__,
            descriptors=self._exposable().values(),
        )
        return card.to_json_dict()

    async def handle_jsonrpc(
        self,
        payload: dict[str, Any],
        *,
        peer_id: str = "",
        auth_header: str = "",
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._error_envelope(None, -32600, _NOT_AN_OBJECT)
        request_id = payload.get("id")
        # BF-876: every method needs the inbound token; outbound_peers tokens never count.
        if not bearer_token_matches(auth_header, self._config.auth_token):
            logger.info(
                "BF-876: refused an A2A request from %r: missing or wrong bearer token",
                peer_id[:80],
            )
            return self._error_envelope(request_id, -32600, _AUTH_FAILED)
        caller = _principal(_BEARER_CALLER) if self._armed else _labelled(peer_id)  # AD-1198 armed: every bearer holder is one caller, and the peer header labels nothing
        return await self._dispatch(payload, caller)

    async def handle_peer_request(self, body: bytes) -> tuple[int, dict[str, Any]] | None:
        """AD-1198 slice 3b: a signed A2A request -- ``(HTTP status, JSON-RPC response)``, or ``None`` when refused.

        ``body`` is an AD-1197 envelope that a pinned peer sealed for this ship (topic ``a2a_request``),
        whose payload is the JSON-RPC request. It is authenticated exactly as an inbound envelope, then
        checked as the bearer door checks a body (400 when it is not a JSON-RPC 2.0 request). The caller
        is the node that signed it, never a header. Without armed peer admission and its federation seam
        every signed request is refused.
        """
        if self._peer_requests is None:  # AD-1198 no armed seam, no signed request
            return None
        authenticated = await self._peer_requests.authenticate_payload(body, topic=A2A_REQUEST)
        if authenticated is None:  # AD-1198 a pinned peer's signed request, admitted once
            return None
        node_id, signed = authenticated
        payload, error = parse_jsonrpc_request(json.dumps(signed).encode())
        if error is not None:  # AD-1198 the signed payload is a JSON-RPC request, as the bearer door requires
            return 400, error
        return 200, await self._dispatch(cast("dict[str, Any]", payload), _principal(f"{_NODE_CALLER}{node_id}"))  # AD-1198 the caller is the node that signed it

    async def _dispatch(self, payload: dict[str, Any], caller: _Caller) -> dict[str, Any]:
        """An authenticated JSON-RPC request, run for ``caller``."""
        request_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error_envelope(request_id, -32602, "Invalid params")

        try:
            if method == "tasks/send":
                return await self._handle_tasks_send(request_id, params, caller)
            if method == "tasks/get":
                return await self._handle_tasks_get(request_id, params, caller.owner)
            if method in (
                "tasks/sendSubscribe",
                "tasks/cancel",
                "tasks/pushNotification/set",
                "tasks/pushNotification/get",
            ):
                return self._error_envelope(
                    request_id, -32601, f"Method not found: {method}"
                )
            return self._error_envelope(
                request_id, -32601, f"Method not found: {str(method)[:80]}"
            )
        except Exception as exc:
            logger.exception("AD-480d: server error handling %s", method)
            return self._error_envelope(
                request_id, -32000, f"Server error: {exc}"
            )

    async def _handle_tasks_send(
        self, request_id: Any, params: dict[str, Any], caller: _Caller
    ) -> dict[str, Any]:
        task_id = str(params.get("id") or uuid.uuid4().hex)
        session_id = str(params.get("sessionId") or "")
        message = params.get("message") or {}
        parts = message.get("parts") if isinstance(message, dict) else None
        if parts is None:  # BF-876: absent or null means no parts; any other non-array is refused below
            parts = []
        if not isinstance(parts, list):  # BF-876: A2A's Message.parts is an array; iterating anything else raised
            return self._error_envelope(request_id, -32602, _BAD_PARTS)
        text = ""
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                text = str(p.get("text") or "")
                break
        skill_id, args = self._parse_text_payload(text)
        if not skill_id:
            return self._error_envelope(
                request_id, -32602, "Invalid params: missing skill_id"
            )
        if args is None:  # BF-876: refused, never run with the caller's arguments dropped
            return self._error_envelope(request_id, -32602, _BAD_ARGUMENTS)
        # BF-876: a listed, declared, never consensus-flagged intent, or nothing -- no peer,
        # trust, task or bus side effect before this point.
        if skill_id not in self._exposable():
            logger.info(
                "BF-876: refused A2A tasks/send %r from %r", skill_id[:80], caller.peer_id[:80]
            )
            return self._error_envelope(
                request_id, -32602, _UNAVAILABLE.format(name=skill_id[:80])
            )

        # Trust onboarding
        if caller.peer_id:
            await self._ensure_peer_registered(caller)

        intent = IntentMessage(
            intent=skill_id,
            params=args,
            context=f"a2a:{caller.peer_id}",
        )
        results = await self._runtime.intent_bus.broadcast(intent, federated=False)
        success = False
        winning = None
        if results:
            for r in sorted(results, key=lambda x: x.confidence, reverse=True):
                if r.success:
                    winning = r
                    break
            if winning is None:
                winning = max(results, key=lambda x: x.confidence)
            success = winning.success

        if caller.peer_id:
            self._runtime.federation_peer_registry.record_outcome(
                caller.peer_id, success, intent_type=skill_id
            )

        artifact_text = json.dumps(
            winning.result if winning is not None else None,
            default=str,
        )
        task = {
            "id": task_id,
            "sessionId": session_id,
            "status": {
                "state": "completed" if success else "failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "artifacts": [
                {"parts": [{"type": "text", "text": artifact_text}]}
            ],
            "history": [],
        }
        await self._store_task(caller.owner, task_id, task)
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": task,
        }

    async def _handle_tasks_get(
        self, request_id: Any, params: dict[str, Any], owner: str
    ) -> dict[str, Any]:
        task_id = str(params.get("id") or "")
        if not task_id:
            return self._error_envelope(
                request_id, -32602, "Invalid params: id required"
            )
        async with self._lock:
            task = self._task_store.get((owner, task_id))  # AD-1198 a caller reads only its own tasks
        if task is None:
            return self._error_envelope(
                request_id, -32602, "Invalid params: task not found"
            )
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": task,
        }

    async def _store_task(self, owner: str, task_id: str, task: dict[str, Any]) -> None:
        async with self._lock:
            self._task_store[(owner, task_id)] = task  # AD-1198 each caller's tasks are its own
            while len(self._task_store) > _TASK_STORE_MAX:
                self._task_store.popitem(last=False)

    def _exposable(self) -> dict[str, IntentDescriptor]:
        """BF-876: listed in exposed_intents, declared by an agent, and never consensus-flagged."""
        return exposable_intents(self._collect_intent_descriptors_fn, self._config.exposed_intents)

    async def _ensure_peer_registered(self, caller: _Caller) -> None:
        from probos.federation.peer import FederationPeer

        await self._runtime.federation_peer_registry.register_peer(
            FederationPeer(
                protocol="a2a",
                peer_id=caller.peer_id,
                endpoint=caller.peer_id,
                trust_record_id=caller.trust_record_id,
            )
        )

    @staticmethod
    def _parse_text_payload(text: str) -> tuple[str, dict[str, Any] | None]:
        """``(skill_id, arguments)``; BF-876: arguments are None unless the text after ``:`` is one JSON object."""
        if not text:
            return "", {}
        if ":" not in text:
            return text.strip(), {}
        skill_id, _, json_part = text.partition(":")
        skill_id = skill_id.strip()
        try:
            args = strict_json_loads(json_part) if json_part.strip() else {}
        except (ValueError, RecursionError):  # BF-876: not JSON, a number JSON cannot hold, or nested too deep
            return skill_id, None
        return skill_id, args if isinstance(args, dict) else None

    @staticmethod
    def _error_envelope(
        request_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return _jsonrpc_error(request_id, code, message)
