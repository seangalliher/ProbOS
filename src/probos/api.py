"""ProbOS HTTP + WebSocket API server (AD-247, AD-254).

FastAPI application providing REST endpoints and a WebSocket event
stream for programmatic access to a running ProbOS runtime.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# AD-516: Models moved to api_models.py — re-export for backwards compatibility
from probos.api_models import (  # noqa: F401
    ChatMessage, ChatRequest, ChatResponse,
    SelfModRequest, EnrichRequest,
    BuildRequest, BuildApproveRequest, BuildResolveRequest,
    BuildQueueApproveRequest, BuildQueueRejectRequest, BuildEnqueueRequest,
    DesignRequest, DesignApproveRequest,
    AgentChatRequest,
    CreateChannelRequest, CreateThreadRequest, UpdateThreadRequest,
    CreatePostRequest, EndorseRequest, ShutdownRequest, SubscribeRequest,
    SkillAssessmentRequest, SkillCommissionRequest,
    CreateAssignmentRequest, ModifyMembersRequest,
    ScheduledTaskRequest, UpdateAgentHintRequest,
)

logger = logging.getLogger(__name__)


# Commands that should NOT be available via the API
_BLOCKED_COMMANDS = {'/quit', '/debug'}

# Cache for failed build contexts — enables resolution endpoint (AD-345)
_pending_failures: dict[str, dict] = {}
_FAILURE_CACHE_TTL = 1800  # 30 minutes


def _clean_expired_failures() -> None:
    """Remove expired entries from the pending failures cache."""
    now = time.time()
    expired = [k for k, v in _pending_failures.items() if now - v.get("timestamp", 0) > _FAILURE_CACHE_TTL]
    for k in expired:
        del _pending_failures[k]


def _strip_rich_formatting(text: str) -> str:
    """Strip Rich panel/table box-drawing characters for clean text output."""
    text = re.sub(r'[─━│┃┌┐└┘├┤┬┴┼╭╮╰╯╋╸╹╺╻═║╔╗╚╝╠╣╦╩╬]', '', text)
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'  +', '  ', text)
    lines = [line.strip() for line in text.split('\n')]
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return '\n'.join(cleaned).strip()


async def _handle_slash_command(text: str, runtime: Any) -> dict[str, Any]:
    """Handle slash commands via the API by delegating to the shell.

    Reuses the existing ProbOSShell command handlers so all 27 slash commands
    work identically in the HXI chat and the CLI terminal.
    """
    parts = text.split(None, 1)
    cmd = parts[0].lower()

    if cmd in _BLOCKED_COMMANDS:
        return {
            "response": f"{cmd} is only available in the CLI terminal, not the HXI chat.",
            "dag": None,
            "results": None,
        }

    from io import StringIO

    try:
        from rich.console import Console
        from probos.experience.shell import ProbOSShell

        output = StringIO()
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
        shell = ProbOSShell(runtime=runtime, console=console)

        await shell.execute_command(text)

        response_text = _strip_rich_formatting(output.getvalue().strip())
        if not response_text:
            response_text = f"Command {text.split()[0]} executed."
    except Exception as e:
        logger.warning("Slash command failed: %s — %s", text, e)
        response_text = f"Command error: {e}"

    return {"response": response_text, "dag": None, "results": None}


def create_app(runtime: Any) -> FastAPI:
    """Build the FastAPI application wired to *runtime*."""

    @asynccontextmanager
    async def _lifespan(app_instance: FastAPI):
        """Application lifespan — drain background tasks on shutdown."""
        yield
        # Shutdown: cancel all tracked background tasks
        if _background_tasks:
            logger.info("Shutting down: cancelling %d background task(s)", len(_background_tasks))
            for task in _background_tasks:
                task.cancel()
            await asyncio.gather(*_background_tasks, return_exceptions=True)
            _background_tasks.clear()

    app = FastAPI(title="ProbOS", version="0.1.0", lifespan=_lifespan)

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

    # Pending architect proposals awaiting Captain approval (AD-308)
    _pending_designs: dict[str, dict[str, Any]] = {}

    # Managed background tasks (AD-326) — track all fire-and-forget pipelines
    _background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

    def _track_task(coro: Any, *, name: str | None = None) -> asyncio.Task:
        """Create a background task and track it in _background_tasks.

        The task is automatically removed from the set when it completes,
        whether by success, failure, or cancellation.
        """
        task = asyncio.create_task(coro, name=name)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return task

    # AD-516: Expose shared state for router dependency injection
    app.state.runtime = runtime
    app.state.track_task = _track_task
    app.state.pending_designs = _pending_designs
    # app.state.broadcast_event set after _broadcast_event is defined (below)

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

    # AD-516: /api/tasks stays in api.py (uses _background_tasks and _pending_designs closures)
    @app.get("/api/tasks")
    async def list_tasks() -> dict[str, Any]:
        """List active background tasks (builds, designs, self-mod)."""
        tasks = []
        for task in _background_tasks:
            tasks.append({
                "name": task.get_name() or "unnamed",
                "done": task.done(),
            })
        return {
            "active_count": sum(1 for t in _background_tasks if not t.done()),
            "total_tracked": len(_background_tasks),
            "pending_designs": len(_pending_designs),
            "tasks": tasks,
        }

    # ── Router registrations (AD-516) ─────────────────────────────────
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph,
    ):
        app.include_router(r.router)

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

    def _safe_serialize(obj: Any) -> Any:
        """Make an object JSON-safe by converting dataclasses and non-serializable types."""
        import json
        import dataclasses
        
        def _default(o: Any) -> Any:
            if dataclasses.is_dataclass(o) and not isinstance(o, type):
                return dataclasses.asdict(o)
            if hasattr(o, '__dict__'):
                return {k: v for k, v in o.__dict__.items() if not k.startswith('_')}
            return str(o)
        
        # Round-trip through json to ensure everything is serializable
        try:
            return json.loads(json.dumps(obj, default=_default))
        except (TypeError, ValueError):
            return {"error": "serialization_failed"}

    def _broadcast_event(event: dict[str, Any]) -> None:
        """Send event to all connected WebSocket clients."""
        safe_event = _safe_serialize(event)

        async def _safe_send(ws: WebSocket, data: dict) -> None:
            try:
                await ws.send_json(data)
            except Exception:
                logger.debug("WS client prune failed", exc_info=True)
                # Client disconnected or errored — prune from list
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

        for ws in list(_ws_clients):
            asyncio.create_task(_safe_send(ws, safe_event))

    # AD-516: Now that _broadcast_event is defined, expose it via app.state
    app.state.broadcast_event = _broadcast_event

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
