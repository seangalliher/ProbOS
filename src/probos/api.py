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
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
        avatars,  # AD-721b-1 (Wave 155): /api/avatars/lipsync
        browser_stream,  # AD-706a: Captain-watch MJPEG streaming
        browser_recordings,  # AD-706b: session recording admin endpoints
        cloud_pickers,  # AD-720c (Wave 168): OAuth cloud file picker
        config as config_router,  # AD-741 (Wave 170): /api/config for HXI Settings
        perception,  # AD-733 (Wave 170): camera frame ingestion
        agent_actions,  # AD-745 (Wave 178): conversation -> action dispatch
        voice,  # AD-705c (Wave 179): wake-word training endpoints
        auth_m365,  # AD-749: M365 OAuth auth endpoints
        work,  # AD-750: Semantic work layer endpoints
        security,  # AD-754: data hardening + forget-this endpoint
        connectors,  # AD-763: M365 connector scoping + scan-config
        threads,  # AD-791 (Wave 193): chat-threads substrate
        artifacts as artifacts_router,  # AD-797 (Wave 195): artifacts pane
        teams_webhook,  # AD-805 (Wave 198): Teams Bot Framework receiver
        task_sessions as task_sessions_router,  # AD-815a (Wave 200): TaskSession
        insights as insights_router,  # AD-810: operator-facing recent-activity summary
        schedule_nl as schedule_nl_router,  # AD-812: NL scheduled actions
        projects as projects_router,  # AD-793 (Wave 196): projects substrate
        capability_requests as capability_requests_router,  # AD-857: capability-request decision surface
        crew_tasks as crew_tasks_router,  # AD-862: crew-collaboration surface
        crew as crew_router,  # AD-892: crew personnel roster + service record
        tools as tools_router,  # AD-894: tool asset catalog
        packs as packs_router,  # AD-1003c: installed Capability-Pack inventory
        mcp_servers as mcp_servers_router,  # AD-1015: MCP server CRUD management API
        workstations as workstations_router,  # AD-1022: workstation-type catalog
        mcp_apps as mcp_apps_router,  # AD-1024: MCP-app gallery read API
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
        avatars,
        browser_stream,
        browser_recordings,
        cloud_pickers,
        config_router,
        perception,
        agent_actions,
        voice,
        auth_m365,
        work,
        security,
        connectors,
        threads,
        artifacts_router,
        teams_webhook,
        task_sessions_router,
        insights_router,
        schedule_nl_router,
        projects_router,
        capability_requests_router,
        crew_tasks_router,
        crew_router,
        tools_router,
        packs_router,
        mcp_servers_router,
        workstations_router,
        mcp_apps_router,
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
        from starlette.types import Scope

        class _CacheAwareStaticFiles(StaticFiles):
            """BF-281 (2026-05-13): emit ``Cache-Control`` headers so browsers
            don't serve a stale ``index.html`` from cache after the Vite bundle
            hash rotates.

            - ``index.html`` (and any ``/`` request that resolves to it) →
              ``no-cache`` so the browser revalidates each load and picks up
              the latest bundle filename.
            - Hashed asset files under ``assets/`` (``index-<hash>.js`` /
              ``index-<hash>.css``) → ``immutable, max-age=31536000`` because
              the hash changes whenever the content changes, so the cache is
              safe to keep forever.
            - Everything else → default StaticFiles behavior.

            The May-12 → May-13 stale-bundle incident (BF-279 + AD-738 silent
            voice fallback) is the canonical case study — see
            ``DECISIONS.md`` AD-738 / BF-281 entries.
            """

            async def get_response(self, path: str, scope: Scope):  # type: ignore[override]
                response = await super().get_response(path, scope)
                _path_lower = path.lower()
                if _path_lower in ("", "/", "index.html"):
                    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                elif _path_lower.startswith("assets/") and (
                    _path_lower.endswith(".js")
                    or _path_lower.endswith(".css")
                    or _path_lower.endswith(".woff")
                    or _path_lower.endswith(".woff2")
                ):
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response

        # BF-305: serve operator-pulled browser-side ML model artifacts under
        # ``/data/<class>/...`` so the UI can fetch Silero VAD + whisper.cpp
        # WASM + ggml model bytes via the same origin as the bundle. Only
        # whitelisted subdirs of the data dir are exposed — the rest of the
        # data dir contains SQLite stores (trust, events, episodes, etc.)
        # which must NEVER be reachable over HTTP. The mounts MUST be added
        # BEFORE the catch-all ``app.mount("/", ...)`` for the HXI bundle,
        # because FastAPI routes by registration order.
        try:
            _data_dir = getattr(runtime, "_data_dir", None) or getattr(runtime, "data_dir", None)
        except Exception:
            _data_dir = None
        if _data_dir is not None:
            _data_dir = Path(_data_dir)
            for _model_subdir in ("silero-vad", "whisper"):
                _model_path = _data_dir / _model_subdir
                # check_dir=False keeps the mount alive even when the operator
                # hasn't pulled the model yet — fetches just 404 cleanly.
                try:
                    _model_path.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                app.mount(
                    f"/data/{_model_subdir}",
                    StaticFiles(directory=str(_model_path), check_dir=False),
                    name=f"data-{_model_subdir}",
                )

        app.mount("/", _CacheAwareStaticFiles(directory=str(_ui_dist), html=True), name="hxi")
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
