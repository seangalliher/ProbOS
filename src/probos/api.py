"""ProbOS HTTP + WebSocket API server (AD-247, AD-254).

FastAPI application providing REST endpoints and a WebSocket event
stream for programmatic access to a running ProbOS runtime.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)


async def _handle_slash_command(text: str, runtime: Any) -> dict[str, Any]:
    """Handle slash commands via the API without going through the decomposer."""
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/feedback":
        if not hasattr(runtime, "record_feedback"):
            return {"response": "Feedback not available", "dag": None, "results": None}
        if arg not in ("good", "bad"):
            return {"response": "Usage: /feedback good|bad", "dag": None, "results": None}
        try:
            result = await runtime.record_feedback(arg == "good")
            if result is None:
                return {"response": "No recent execution to rate.", "dag": None, "results": None}
            return {"response": f"\u2713 Feedback recorded ({arg})", "dag": None, "results": None}
        except Exception as e:
            return {"response": f"Feedback error: {e}", "dag": None, "results": None}

    if cmd == "/correct":
        if arg:
            dag_result = await runtime.process_natural_language(arg)
            response_text = dag_result.get("response", "") if dag_result else ""
            correction = dag_result.get("correction") if dag_result else None
            if correction:
                response_text = f"Correction applied: {correction.get('changes', 'OK')}"
            return {"response": response_text or "Correction processed", "dag": None, "results": None}
        return {"response": "Usage: /correct <what to fix>", "dag": None, "results": None}

    if cmd == "/status":
        status = runtime.status()
        return {
            "response": f"Agents: {status.get('total_agents', 0)}, "
                        f"Health: {status.get('overall_health', 'N/A')}",
            "dag": None,
            "results": None,
        }

    # Unknown slash command — pass through as NL
    dag_result = await runtime.process_natural_language(text)
    response_text = dag_result.get("response", "") if dag_result else ""
    return {"response": response_text or f"Unknown command: {cmd}", "dag": None, "results": None}


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    dag: dict[str, Any] | None = None
    results: dict[str, Any] | None = None


def create_app(runtime: Any) -> FastAPI:
    """Build the FastAPI application wired to *runtime*."""

    app = FastAPI(title="ProbOS", version="0.1.0")

    # CORS for HXI dev server (AD-260)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                        "http://localhost:18900", "http://127.0.0.1:18900"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Active WebSocket connections for event broadcasting
    _ws_clients: list[WebSocket] = []

    # ------------------------------------------------------------------
    # Event listener bridge: runtime -> WebSocket clients (AD-254)
    # ------------------------------------------------------------------

    def _on_runtime_event(event: dict[str, Any]) -> None:
        """Forward runtime events to all connected WebSocket clients."""
        _broadcast_event(event)

    if hasattr(runtime, 'add_event_listener'):
        runtime.add_event_listener(_on_runtime_event)

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
        text = req.message.strip()

        # Handle slash commands directly (don't send through NL decomposer)
        if text.startswith('/'):
            return await _handle_slash_command(text, runtime)

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

        if not dag_result:
            return {"response": "(Processing failed)", "dag": None, "results": None}

        logger.info(
            "dag_result keys: %s", list(dag_result.keys()),
        )
        logger.info(
            "dag_result response: %r", dag_result.get("response"),
        )

        response_text = dag_result.get("response", "") or ""

        dag_obj = dag_result.get("dag")
        dag_dict: dict[str, Any] | None = None
        if dag_obj and hasattr(dag_obj, "source_text"):
            dag_dict = {
                "source_text": getattr(dag_obj, "source_text", ""),
                "reflect": getattr(dag_obj, "reflect", False),
            }

        results_dict: dict[str, Any] | None = dag_result.get("results", None)

        # Extract reflection if present and no direct response
        reflection = dag_result.get("reflection", "")
        if reflection and not response_text:
            response_text = reflection

        # Extract correction info
        correction = dag_result.get("correction")
        if correction and not response_text:
            response_text = correction.get("changes", "Correction applied")

        # Extract from execution results if still no response text
        # (Path 3: functional DAG — output is inside results[node_id])
        if not response_text and results_dict:
            parts: list[str] = []
            for _node_id, node_result in results_dict.items():
                if isinstance(node_result, dict):
                    # Error case
                    if "error" in node_result:
                        parts.append(f"Error: {node_result['error']}")
                        continue
                    # Normal intent results — list of IntentResult dataclasses
                    intent_results = node_result.get("results")
                    if isinstance(intent_results, list):
                        for r in intent_results:
                            # IntentResult is a dataclass with .result, .error, .success
                            if hasattr(r, "result") and r.result is not None:
                                val = r.result
                                if isinstance(val, dict) and "stdout" in val:
                                    out = val["stdout"]
                                    if val.get("stderr"):
                                        out += f"\n{val['stderr']}"
                                    parts.append(str(out))
                                else:
                                    parts.append(str(val))
                            elif hasattr(r, "error") and r.error:
                                parts.append(f"Error: {r.error}")
                            elif isinstance(r, dict):
                                out = r.get("output") or r.get("result") or r.get("text")
                                if out:
                                    parts.append(str(out))
                    # Single output field
                    elif "output" in node_result:
                        parts.append(str(node_result["output"]))
                elif isinstance(node_result, str) and node_result:
                    parts.append(node_result)
            if parts:
                response_text = "\n".join(parts)
            else:
                logger.info("dag_result results_dict: %r", results_dict)

        # Diagnose empty response — check decomposer state for LLM issues
        if not response_text:
            diag_parts: list[str] = []
            decomposer = getattr(runtime, "decomposer", None)
            if decomposer:
                raw = getattr(decomposer, "last_raw_response", "")
                tier = getattr(decomposer, "last_tier", "")
                model = getattr(decomposer, "last_model", "")
                logger.warning(
                    "Empty response. Decomposer: tier=%s model=%s "
                    "raw_len=%d node_count=%d",
                    tier, model, len(raw),
                    dag_result.get("node_count", -1),
                )
                if not raw and not tier:
                    diag_parts.append(
                        "LLM not connected — check that Ollama is running "
                        "and the model is loaded (run: ollama list)"
                    )
                elif raw and not response_text:
                    diag_parts.append(
                        f"LLM responded but produced no output. "
                        f"Tier: {tier}, Model: {model}"
                    )

            # Live connectivity check
            llm_client = getattr(runtime, "llm_client", None)
            if llm_client and hasattr(llm_client, "check_connectivity"):
                try:
                    connectivity = await llm_client.check_connectivity()
                    unreachable = [t for t, v in connectivity.items() if not v]
                    if unreachable:
                        diag_parts.append(
                            f"Unreachable LLM tiers: {', '.join(unreachable)}"
                        )
                    logger.warning("LLM connectivity: %s", connectivity)
                except Exception:
                    pass

            if diag_parts:
                response_text = " | ".join(diag_parts)
            else:
                response_text = (
                    "(Empty response — check probos serve terminal)"
                )

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
            # Send full state snapshot on connect (AD-254)
            if hasattr(runtime, 'build_state_snapshot'):
                snapshot = runtime.build_state_snapshot()
                await websocket.send_json({
                    "type": "state_snapshot",
                    "data": snapshot,
                    "timestamp": time.time(),
                })

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

    # ------------------------------------------------------------------
    # Static file serving for HXI frontend (AD-260)
    # ------------------------------------------------------------------

    _ui_dist = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"
    if _ui_dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_ui_dist), html=True), name="hxi")
    else:
        from fastapi.responses import HTMLResponse

        @app.get("/")
        async def hxi_fallback() -> HTMLResponse:
            return HTMLResponse(
                "<html><body style='background:#0a0a12;color:#e0dcd4;font-family:monospace;"
                "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
                "<div style='text-align:center'>"
                "<h1>ProbOS HXI</h1>"
                "<p>Frontend not built. Run:</p>"
                "<pre style='color:#f0b060'>cd ui && npm install && npm run build</pre>"
                "<p style='color:#8888a0'>API endpoints are available at /api/*</p>"
                "</div></body></html>"
            )

    return app
