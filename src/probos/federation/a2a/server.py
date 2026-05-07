"""AD-480d: FederationA2AServer -- inbound A2A server.

ProbOS-as-A2A-server. Hosts /.well-known/agent.json and JSON-RPC tasks/send
+ tasks/get synchronously. Streaming (tasks/sendSubscribe) and push
(tasks/pushNotification/*) parked at AD-480j / AD-480m.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.config import FederationA2AConfig
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


JSONRPC_VERSION = "2.0"

_TASK_STORE_MAX = 1000


class FederationA2AServer:
    def __init__(
        self,
        *,
        runtime: "ProbOSRuntime",
        config: "FederationA2AConfig",
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._task_store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
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
                "AD-480d: starlette/uvicorn missing; A2A server disabled"
            )
            return

        async def agent_card_endpoint(request):
            payload = await self.handle_agent_card_request()
            return JSONResponse(payload)

        async def jsonrpc_endpoint(request):
            body = await request.body()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse(
                    self._error_envelope(None, -32700, "Parse error"),
                    status_code=400,
                )
            peer_id = request.headers.get("x-a2a-peer-id", "") or (
                request.client.host if request.client else ""
            )
            auth_header = request.headers.get("authorization", "")
            response = await self.handle_jsonrpc(
                payload, peer_id=peer_id, auth_header=auth_header
            )
            return JSONResponse(response)

        app = Starlette(
            routes=[
                Route(
                    self._config.agent_card_path or "/.well-known/agent.json",
                    agent_card_endpoint,
                    methods=["GET"],
                ),
                Route("/a2a", jsonrpc_endpoint, methods=["POST"]),
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
        card = AgentCard.from_runtime(
            self._runtime, base_url=base_url, version=__version__
        )
        return card.to_json_dict()

    async def handle_jsonrpc(
        self,
        payload: dict[str, Any],
        *,
        peer_id: str = "",
        auth_header: str = "",
    ) -> dict[str, Any]:
        request_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error_envelope(request_id, -32602, "Invalid params")

        # Auth check (static bearer in v1; full OAuth at AD-480k)
        if not self._auth_ok(peer_id, auth_header):
            return self._error_envelope(
                request_id, -32600, "Invalid Request: authentication failed"
            )

        try:
            if method == "tasks/send":
                return await self._handle_tasks_send(request_id, params, peer_id)
            if method == "tasks/get":
                return await self._handle_tasks_get(request_id, params)
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
                request_id, -32601, f"Method not found: {method}"
            )
        except Exception as exc:
            logger.exception("AD-480d: server error handling %s", method)
            return self._error_envelope(
                request_id, -32000, f"Server error: {exc}"
            )

    def _auth_ok(self, peer_id: str, auth_header: str) -> bool:
        expected = ""
        for entry in self._config.outbound_peers:
            if entry.peer_url and peer_id and entry.peer_url == peer_id:
                expected = entry.auth_token
                break
        if not expected:
            return True
        if not auth_header.lower().startswith("bearer "):
            return False
        return auth_header.split(None, 1)[1].strip() == expected

    async def _handle_tasks_send(
        self, request_id: Any, params: dict[str, Any], peer_id: str
    ) -> dict[str, Any]:
        task_id = str(params.get("id") or uuid.uuid4().hex)
        session_id = str(params.get("sessionId") or "")
        message = params.get("message") or {}
        parts = (message.get("parts") if isinstance(message, dict) else None) or []
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

        # Trust onboarding
        if peer_id:
            await self._ensure_peer_registered(peer_id)

        intent = IntentMessage(
            intent=skill_id,
            params=args,
            context=f"a2a:{peer_id}",
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

        if peer_id:
            self._runtime.federation_peer_registry.record_outcome(
                peer_id, success, intent_type=skill_id
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
        await self._store_task(task_id, task)
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": task,
        }

    async def _handle_tasks_get(
        self, request_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        task_id = str(params.get("id") or "")
        if not task_id:
            return self._error_envelope(
                request_id, -32602, "Invalid params: id required"
            )
        async with self._lock:
            task = self._task_store.get(task_id)
        if task is None:
            return self._error_envelope(
                request_id, -32602, "Invalid params: task not found"
            )
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": task,
        }

    async def _store_task(self, task_id: str, task: dict[str, Any]) -> None:
        async with self._lock:
            self._task_store[task_id] = task
            while len(self._task_store) > _TASK_STORE_MAX:
                self._task_store.popitem(last=False)

    async def _ensure_peer_registered(self, peer_id: str) -> None:
        from probos.federation.peer import FederationPeer

        await self._runtime.federation_peer_registry.register_peer(
            FederationPeer(
                protocol="a2a",
                peer_id=peer_id,
                endpoint=peer_id,
                trust_record_id=f"a2a-peer:{peer_id}",
            )
        )

    @staticmethod
    def _parse_text_payload(text: str) -> tuple[str, dict[str, Any]]:
        if not text:
            return "", {}
        if ":" not in text:
            return text.strip(), {}
        skill_id, _, json_part = text.partition(":")
        skill_id = skill_id.strip()
        try:
            args = json.loads(json_part) if json_part.strip() else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return skill_id, args

    @staticmethod
    def _error_envelope(
        request_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }
