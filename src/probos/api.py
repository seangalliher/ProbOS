"""ProbOS HTTP + WebSocket API server (AD-247).

FastAPI application providing REST endpoints and a WebSocket event
stream for programmatic access to a running ProbOS runtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    dag: dict[str, Any] | None = None
    results: dict[str, Any] | None = None


def create_app(runtime: Any) -> FastAPI:
    """Build the FastAPI application wired to *runtime*."""

    app = FastAPI(title="ProbOS", version="0.1.0")

    # Active WebSocket connections for event broadcasting
    _ws_clients: list[WebSocket] = []

    # ------------------------------------------------------------------
    # REST endpoints
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        status = runtime.status()
        return {
            "status": "ok",
            "agents": status.get("total_agents", 0),
            "health": round(
                sum(
                    a.confidence
                    for a in runtime.registry.all()
                ) / max(1, runtime.registry.count),
                2,
            ),
        }

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return runtime.status()

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        events: list[dict[str, Any]] = []

        async def on_event(event_type: str, data: dict[str, Any] | None = None) -> None:
            evt = {
                "type": event_type,
                "data": data or {},
                "timestamp": time.time(),
            }
            events.append(evt)
            # Broadcast to WebSocket clients (fire-and-forget)
            _broadcast_event(evt)

        dag_result = await runtime.process_natural_language(
            req.message, on_event=on_event,
        )

        response_text = ""
        dag_dict: dict[str, Any] | None = None
        results_dict: dict[str, Any] | None = None

        if dag_result:
            response_text = getattr(dag_result, "response", "") or ""
            dag_dict = {
                "source_text": getattr(dag_result, "source_text", ""),
                "reflect": getattr(dag_result, "reflect", False),
            }
            results_dict = {}
            for node in getattr(dag_result, "nodes", []):
                results_dict[node.id] = {
                    "intent": node.intent,
                    "status": node.status,
                    "result": node.result,
                    "output": node.output,
                }

        return {
            "response": response_text,
            "dag": dag_dict,
            "results": results_dict,
        }

    # ------------------------------------------------------------------
    # WebSocket event stream
    # ------------------------------------------------------------------

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket) -> None:
        await websocket.accept()
        _ws_clients.append(websocket)
        try:
            # Keep connection alive — client can send pings
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send a keepalive ping
                    await websocket.send_json({"type": "ping", "timestamp": time.time()})
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)

    def _broadcast_event(event: dict[str, Any]) -> None:
        """Send event to all connected WebSocket clients."""
        for ws in list(_ws_clients):
            try:
                asyncio.create_task(ws.send_json(event))
            except Exception:
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

    return app
