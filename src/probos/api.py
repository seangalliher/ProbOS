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

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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


class ChatMessage(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str
    dag: dict[str, Any] | None = None
    results: dict[str, Any] | None = None


class SelfModRequest(BaseModel):
    intent_name: str
    intent_description: str
    parameters: dict[str, str] = {}
    original_message: str = ""


class EnrichRequest(BaseModel):
    intent_name: str
    intent_description: str
    parameters: dict[str, str] = {}
    user_guidance: str


class BuildRequest(BaseModel):
    """Request to trigger the BuilderAgent."""
    title: str
    description: str
    target_files: list[str] = []
    reference_files: list[str] = []
    test_files: list[str] = []
    ad_number: int = 0
    constraints: list[str] = []
    force_native: bool = False
    force_visiting: bool = False
    model: str = ""


class BuildApproveRequest(BaseModel):
    """Request to approve and execute a generated build."""
    build_id: str
    file_changes: list[dict[str, Any]] = []
    title: str = ""
    description: str = ""
    ad_number: int = 0
    branch_name: str = ""


class BuildResolveRequest(BaseModel):
    """Request to resolve a failed build (AD-345)."""
    build_id: str
    resolution: str  # "retry_extended", "retry_targeted", "retry_fix", "commit_override", "abort"


class BuildQueueApproveRequest(BaseModel):
    """Request to approve a queued build — merge to main (AD-375)."""
    build_id: str


class BuildQueueRejectRequest(BaseModel):
    """Request to reject a queued build (AD-375)."""
    build_id: str


class BuildEnqueueRequest(BaseModel):
    """Request to add a build spec to the dispatch queue (AD-375)."""
    title: str
    description: str = ""
    target_files: list[str] = []
    reference_files: list[str] = []
    test_files: list[str] = []
    ad_number: int = 0
    constraints: list[str] = []
    priority: int = 5


class DesignRequest(BaseModel):
    """Request to trigger the ArchitectAgent."""
    feature: str
    phase: str = ""


class DesignApproveRequest(BaseModel):
    """Request to approve an architect proposal — forwards BuildSpec to builder."""
    design_id: str


class AgentChatRequest(BaseModel):
    """Request to send a direct message to a specific agent."""
    message: str
    history: list[dict[str, str]] = []  # AD-430b: conversation history from HXI


# Ward Room models (AD-407)

class CreateChannelRequest(BaseModel):
    name: str
    description: str = ""
    created_by: str  # agent_id

class CreateThreadRequest(BaseModel):
    author_id: str
    title: str
    body: str
    author_callsign: str = ""
    thread_mode: str = "discuss"      # AD-424
    max_responders: int = 0           # AD-424

class UpdateThreadRequest(BaseModel):
    """AD-424: Captain thread management."""
    locked: bool | None = None
    thread_mode: str | None = None     # "inform" | "discuss" | "action"
    max_responders: int | None = None
    pinned: bool | None = None

class CreatePostRequest(BaseModel):
    author_id: str
    body: str
    parent_id: str | None = None
    author_callsign: str = ""

class EndorseRequest(BaseModel):
    voter_id: str
    direction: str  # "up" | "down" | "unvote"

class ShutdownRequest(BaseModel):
    reason: str = ""

class SubscribeRequest(BaseModel):
    agent_id: str
    action: str = "subscribe"  # "subscribe" | "unsubscribe"


# Skill Framework models (AD-428)

class SkillAssessmentRequest(BaseModel):
    skill_id: str
    new_level: int             # ProficiencyLevel value (1-7)
    source: str = "assessment"
    notes: str = ""

class SkillCommissionRequest(BaseModel):
    agent_type: str


# Assignment models (AD-408)

class CreateAssignmentRequest(BaseModel):
    name: str
    assignment_type: str  # "bridge" | "away_team" | "working_group"
    members: list[str]    # agent_ids
    created_by: str = "captain"
    mission: str = ""

class ModifyMembersRequest(BaseModel):
    agent_id: str
    action: str = "add"  # "add" | "remove"

class ScheduledTaskRequest(BaseModel):
    """Request to create a persistent scheduled task (Phase 25a)."""
    intent_text: str
    name: str = ""
    schedule_type: str = "once"   # once | interval | cron
    execute_at: float | None = None
    interval_seconds: float | None = None
    cron_expr: str | None = None
    channel_id: str | None = None
    max_runs: int | None = None
    created_by: str = "captain"
    webhook_name: str | None = None
    agent_hint: str | None = None            # AD-418


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

    @app.get("/api/system/services")
    async def system_services() -> dict[str, Any]:
        """AD-436: Service status for Bridge System panel."""
        services = []
        checks = [
            ("Ward Room", runtime.ward_room),
            ("Episodic Memory", runtime.episodic_memory),
            ("Trust Network", runtime.trust_network),
            ("Knowledge Store", getattr(runtime, '_knowledge_store', None)),
            ("Cognitive Journal", getattr(runtime, 'cognitive_journal', None)),
            ("Codebase Index", getattr(runtime, 'codebase_index', None)),
            ("Skill Framework", getattr(runtime, 'skill_registry', None)),
            ("Skill Service", getattr(runtime, 'skill_service', None)),
            ("ACM", getattr(runtime, 'acm', None)),
            ("Hebbian Router", getattr(runtime, 'hebbian_router', None)),
            ("Intent Bus", getattr(runtime, 'intent_bus', None)),
        ]
        for name, svc in checks:
            if svc is None:
                status = "offline"
            else:
                status = "online"
            services.append({"name": name, "status": status})
        return {"services": services}

    @app.get("/api/system/circuit-breakers")
    async def system_circuit_breakers() -> dict[str, Any]:
        """AD-488: Circuit breaker status for all tracked agents."""
        if not hasattr(runtime, 'proactive_loop') or not runtime.proactive_loop:
            return {"breakers": []}
        cb = runtime.proactive_loop.circuit_breaker
        statuses = cb.get_all_statuses()
        # Enrich with callsigns
        for s in statuses:
            agent = runtime.registry.get(s["agent_id"])
            if agent:
                s["callsign"] = getattr(agent, 'callsign', agent.agent_type)
        return {"breakers": statuses}

    @app.post("/api/system/shutdown")
    async def system_shutdown(req: ShutdownRequest) -> dict[str, Any]:
        """AD-436: Initiate system shutdown from HXI Bridge."""
        async def _do_shutdown():
            await asyncio.sleep(1)  # Let response return first
            await runtime.stop(reason=req.reason)
        _track_task(_do_shutdown(), name="system-shutdown")
        return {"status": "shutting_down", "reason": req.reason}

    # --- Ontology endpoints (AD-429a) ---

    @app.get("/api/ontology/vessel")
    async def get_vessel() -> Any:
        """Vessel identity and state."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        from dataclasses import asdict
        return {
            "identity": asdict(runtime.ontology.get_vessel_identity()),
            "state": asdict(runtime.ontology.get_vessel_state()),
        }

    @app.get("/api/ontology/organization")
    async def get_organization() -> Any:
        """Full org chart: departments, posts, assignments, chain of command."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        from dataclasses import asdict
        ont = runtime.ontology
        return {
            "departments": [asdict(d) for d in ont.get_departments()],
            "posts": [asdict(p) for p in ont.get_posts()],
            "assignments": [asdict(a) for a in ont._assignments.values()],
        }

    @app.get("/api/ontology/crew/{agent_type}")
    async def get_crew_member(agent_type: str) -> Any:
        """Agent's full ontology context — identity, post, department, chain of command."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        ctx = runtime.ontology.get_crew_context(agent_type)
        if not ctx:
            return JSONResponse({"error": "Agent not found in ontology"}, status_code=404)
        return ctx

    @app.get("/api/ontology/skills/{agent_type}")
    async def get_ontology_skills(agent_type: str) -> Any:
        """Agent's skill context — role template, current profile, qualification status."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)

        role_template = runtime.ontology.get_role_template_for_agent(agent_type)
        result: dict[str, Any] = {"agent_type": agent_type}

        if role_template:
            result["role_template"] = {
                "post_id": role_template.post_id,
                "required": [
                    {"skill_id": r.skill_id, "min_proficiency": r.min_proficiency}
                    for r in role_template.required_skills
                ],
                "optional": [
                    {"skill_id": o.skill_id, "min_proficiency": o.min_proficiency}
                    for o in role_template.optional_skills
                ],
            }
        else:
            result["role_template"] = None

        # Include current skill profile if available
        if runtime.skill_service:
            assignment = runtime.ontology.get_assignment_for_agent(agent_type)
            if assignment and assignment.agent_id:
                profile = await runtime.skill_service.get_profile(assignment.agent_id)
                if profile:
                    result["profile"] = profile.to_dict()

        # Include qualification paths
        result["qualification_paths"] = [
            {
                "path_id": f"{qp.from_rank}_to_{qp.to_rank}",
                "description": qp.description,
                "requirements": [
                    {"type": r.type, "description": r.description,
                     "min_proficiency": r.min_proficiency, "scope": r.scope,
                     "min_count": r.min_count}
                    for r in qp.requirements
                ],
            }
            for qp in runtime.ontology.get_all_qualification_paths()
        ]

        return result

    @app.get("/api/ontology/operations")
    async def get_ontology_operations() -> Any:
        """Operations domain — standing order tiers, watch types, alert procedures, duties."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        from dataclasses import asdict
        ont = runtime.ontology
        return {
            "standing_order_tiers": [asdict(t) for t in ont.get_standing_order_tiers()],
            "watch_types": [asdict(w) for w in ont.get_watch_types()],
            "alert_procedures": {k: asdict(v) for k, v in ont._alert_procedures.items()},
            "duty_categories": [asdict(d) for d in ont.get_duty_categories()],
        }

    @app.get("/api/ontology/communication")
    async def get_ontology_communication() -> Any:
        """Communication domain — channel types, thread modes, message patterns."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        from dataclasses import asdict
        ont = runtime.ontology
        return {
            "channel_types": [asdict(c) for c in ont.get_channel_types()],
            "thread_modes": [asdict(t) for t in ont.get_thread_modes()],
            "message_patterns": [asdict(m) for m in ont.get_message_patterns()],
        }

    @app.get("/api/ontology/resources")
    async def get_ontology_resources() -> Any:
        """Resources domain — model tiers, tool capabilities, knowledge sources."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        from dataclasses import asdict
        ont = runtime.ontology
        return {
            "model_tiers": [asdict(m) for m in ont.get_model_tiers()],
            "tool_capabilities": [asdict(t) for t in ont.get_tool_capabilities()],
            "knowledge_sources": [asdict(k) for k in ont.get_knowledge_sources()],
        }

    @app.get("/api/ontology/records")
    async def get_ontology_records() -> Any:
        """Records domain — knowledge tiers, classifications, document classes, retention."""
        if not runtime.ontology:
            return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
        from dataclasses import asdict
        ont = runtime.ontology
        return {
            "knowledge_tiers": [asdict(kt) for kt in ont.get_knowledge_tiers()],
            "classifications": [asdict(c) for c in ont.get_classifications()],
            "document_classes": [asdict(dc) for dc in ont.get_document_classes()],
            "retention_policies": [asdict(rp) for rp in ont.get_retention_policies()],
            "repository_structure": [asdict(d) for d in ont.get_repository_structure()],
        }

    # ── Ward Room DMs API (AD-453/AD-485) ───────────────────────────

    @app.get("/api/wardroom/dms")
    async def list_dm_channels():
        """List all DM channels with latest thread info. Captain oversight."""
        if not runtime.ward_room:
            return []
        channels = await runtime.ward_room.list_channels()
        dm_channels = [c for c in channels if c.channel_type == "dm"]
        result = []
        for ch in dm_channels:
            threads = await runtime.ward_room.list_threads(ch.id, limit=1)
            all_threads = await runtime.ward_room.list_threads(ch.id, limit=100)
            result.append({
                "channel": {
                    "id": ch.id, "name": ch.name,
                    "description": ch.description,
                    "created_at": ch.created_at,
                },
                "latest_thread": threads[0] if threads else None,
                "thread_count": len(all_threads),
            })
        return result

    @app.get("/api/wardroom/dms/{channel_id}/threads")
    async def list_dm_threads(channel_id: str):
        """List all threads in a DM channel. Captain oversight."""
        if not runtime.ward_room:
            raise HTTPException(status_code=404, detail="Ward Room not available")
        channels = await runtime.ward_room.list_channels()
        dm_ch = next((c for c in channels if c.id == channel_id and c.channel_type == "dm"), None)
        if not dm_ch:
            raise HTTPException(status_code=404, detail="DM channel not found")
        threads = await runtime.ward_room.list_threads(channel_id, limit=100)
        return {"channel": dm_ch, "threads": threads}

    @app.get("/api/wardroom/captain-dms")
    async def list_captain_dms():
        """List all DMs addressed to the Captain."""
        if not runtime.ward_room:
            return []
        channels = await runtime.ward_room.list_channels()
        captain_channels = [c for c in channels
                            if c.channel_type == "dm" and "captain" in c.name.lower()]
        result = []
        for ch in captain_channels:
            threads = await runtime.ward_room.list_threads(ch.id, limit=20)
            result.append({
                "channel": {"id": ch.id, "name": ch.name, "description": ch.description,
                            "created_at": ch.created_at},
                "threads": threads,
                "thread_count": len(threads),
            })
        return result

    @app.get("/api/wardroom/dms/archive")
    async def search_dm_archive(q: str = "", since: float = 0, until: float = 0):
        """Search archived DM messages. Captain oversight."""
        if not runtime.ward_room:
            return {"results": [], "count": 0}
        channels = await runtime.ward_room.list_channels()
        dm_channels = [c for c in channels if c.channel_type == "dm"]
        results = []
        for ch in dm_channels:
            threads = await runtime.ward_room.list_threads(
                ch.id, limit=200, include_archived=True
            )
            for t in threads:
                _title = getattr(t, 'title', '') or ''
                _body = getattr(t, 'body', '') or ''
                _created = getattr(t, 'created_at', 0) or 0
                if q and q.lower() not in (_title + _body).lower():
                    continue
                if since and _created < since:
                    continue
                if until and _created > until:
                    continue
                results.append({"channel": ch.name, "thread": t})
        return {"results": results, "count": len(results)}

    # ── Communications Settings API (AD-485) ──────────────────────

    @app.get("/api/system/communications/settings")
    async def get_communications_settings():
        """Get current communications settings."""
        return {
            "dm_min_rank": runtime.config.communications.dm_min_rank,
        }

    @app.patch("/api/system/communications/settings")
    async def update_communications_settings(body: dict):
        """Update communications settings. Captain only."""
        valid_ranks = ["ensign", "lieutenant", "commander", "senior"]
        if "dm_min_rank" in body:
            rank_val = body["dm_min_rank"].lower()
            if rank_val not in valid_ranks:
                raise HTTPException(status_code=400, detail=f"Invalid rank. Must be one of: {valid_ranks}")
            runtime.config.communications.dm_min_rank = rank_val
        return await get_communications_settings()

    # ── Ship's Records API (AD-434) ────────────────────────────────

    @app.get("/api/records/stats")
    async def get_records_stats() -> Any:
        """Get Ship's Records repository statistics."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        return await runtime._records_store.get_stats()

    @app.get("/api/records/documents")
    async def list_records(
        directory: str = "",
        author: str = "",
        status: str = "",
        classification: str = "",
    ) -> Any:
        """List documents in Ship's Records."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        entries = await runtime._records_store.list_entries(
            directory=directory, author=author, status=status, classification=classification,
        )
        return {"documents": entries, "count": len(entries)}

    @app.get("/api/records/documents/{path:path}")
    async def read_record(path: str, reader: str = "captain") -> Any:
        """Read a specific document from Ship's Records."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        entry = await runtime._records_store.read_entry(path, reader_id=reader)
        if entry is None:
            return JSONResponse({"error": "Not found or access denied"}, status_code=404)
        return entry

    @app.post("/api/records/captains-log")
    async def post_captains_log(request: Request) -> Any:
        """Append a Captain's Log entry."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        body = await request.json()
        content = body.get("content", "")
        if not content:
            return JSONResponse({"error": "content required"}, status_code=400)
        path = await runtime._records_store.append_captains_log(content, body.get("message", ""))
        return {"path": path, "status": "appended"}

    @app.get("/api/records/captains-log")
    async def get_captains_log(limit: int = 7) -> Any:
        """Get recent Captain's Log entries."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        entries = await runtime._records_store.list_entries("captains-log")
        entries.sort(key=lambda e: e.get("frontmatter", {}).get("created", ""), reverse=True)
        return {"entries": entries[:limit]}

    @app.get("/api/records/notebooks/{callsign}")
    async def list_notebook(callsign: str) -> Any:
        """List a crew member's notebook entries."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        entries = await runtime._records_store.list_entries(f"notebooks/{callsign}")
        return {"callsign": callsign, "entries": entries}

    @app.post("/api/records/notebooks/{callsign}")
    async def write_notebook_entry(callsign: str, request: Request) -> Any:
        """Write to a crew member's notebook."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        body = await request.json()
        topic = body.get("topic", "untitled")
        content = body.get("content", "")
        if not content:
            return JSONResponse({"error": "content required"}, status_code=400)
        path = await runtime._records_store.write_notebook(
            callsign=callsign,
            topic_slug=topic,
            content=content,
            department=body.get("department", ""),
            tags=body.get("tags", []),
            classification=body.get("classification", "department"),
        )
        return {"path": path, "status": "written"}

    @app.get("/api/records/search")
    async def search_records(q: str = "", scope: str = "ship") -> Any:
        """Search Ship's Records by keyword."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        if not q:
            return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
        results = await runtime._records_store.search(q, scope=scope)
        return {"query": q, "results": results, "count": len(results)}

    @app.get("/api/records/history/{path:path}")
    async def get_record_history(path: str, limit: int = 20) -> Any:
        """Get git history for a specific record."""
        if not runtime._records_store:
            return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
        history = await runtime._records_store.get_history(path, limit=limit)
        return {"path": path, "history": history}

    # ── Identity Endpoints (AD-441) ─────────────────────────────────

    @app.get("/api/agent/{agent_id}/identity")
    async def get_agent_identity(agent_id: str) -> Any:
        """Return the agent's birth certificate and DID."""
        if not runtime.identity_registry:
            return JSONResponse({"error": "Identity registry not available"}, status_code=503)

        cert = runtime.identity_registry.get_by_slot(agent_id)
        if not cert:
            return JSONResponse({"error": "No birth certificate found"}, status_code=404)

        return {
            "sovereign_id": cert.agent_uuid,
            "did": cert.did,
            "birth_certificate": cert.to_verifiable_credential(),
        }

    @app.get("/api/identity/ledger")
    async def get_identity_ledger() -> Any:
        """Return the Identity Ledger status and chain verification."""
        if not runtime.identity_registry:
            return JSONResponse({"error": "Identity registry not available"}, status_code=503)

        valid, message = await runtime.identity_registry.verify_chain()
        chain = await runtime.identity_registry.export_chain()

        return {
            "valid": valid,
            "message": message,
            "block_count": len(chain),
            "chain": chain,
        }

    @app.get("/api/identity/certificates")
    async def list_birth_certificates() -> Any:
        """Return all birth certificates on this ship."""
        if not runtime.identity_registry:
            return JSONResponse({"error": "Identity registry not available"}, status_code=503)

        certs = runtime.identity_registry.get_all()
        return {
            "count": len(certs),
            "certificates": [c.to_verifiable_credential() for c in certs],
        }

    @app.get("/api/identity/ship")
    async def get_ship_identity() -> Any:
        """Return the ship's birth certificate and commissioning data."""
        if not runtime.identity_registry:
            return JSONResponse({"error": "Identity registry not available"}, status_code=503)

        cert = runtime.identity_registry.get_ship_certificate()
        if not cert:
            return JSONResponse({"error": "Ship not commissioned"}, status_code=404)

        return {
            "ship_did": cert.ship_did,
            "instance_id": cert.instance_id,
            "vessel_name": cert.vessel_name,
            "commissioned_at": cert.commissioned_at,
            "birth_certificate": cert.to_verifiable_credential(),
        }

    @app.get("/api/identity/assets")
    async def list_asset_tags() -> Any:
        """Return all asset tags for infrastructure and utility agents."""
        if not runtime.identity_registry:
            return JSONResponse({"error": "Identity registry not available"}, status_code=503)

        tags = runtime.identity_registry.get_asset_tags()
        return {
            "count": len(tags),
            "assets": [t.to_dict() for t in tags],
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        text = req.message.strip()

        # Handle slash commands directly (don't send through NL decomposer)
        if text.startswith('/'):
            # /build command handled here (needs _run_build closure) — AD-304
            parts = text.split(None, 1)
            if parts[0].lower() == "/build":
                args = parts[1] if len(parts) > 1 else ""
                build_parts = args.split(":", 1) if args else ["", ""]
                title = build_parts[0].strip()
                description = build_parts[1].strip() if len(build_parts) > 1 else ""
                if not title:
                    return {"response": "Usage: /build <title>: <description>", "dag": None, "results": None}
                import uuid
                build_id = uuid.uuid4().hex[:12]
                _track_task(_run_build(
                    BuildRequest(title=title, description=description),
                    build_id,
                    runtime,
                ), name=f"build-{build_id}")
                return {
                    "response": f"Build '{title}' submitted (id: {build_id}). Progress will appear below.",
                    "build_id": build_id,
                    "dag": None,
                    "results": None,
                }
            # /design command handled here (needs _run_design closure) — AD-308
            elif parts[0].lower() == "/design":
                args = parts[1] if len(parts) > 1 else ""
                design_parts = args.split(":", 1) if args else ["", ""]
                feature = design_parts[0].strip()
                phase = ""
                if len(design_parts) > 1:
                    feature = design_parts[1].strip()
                    phase = design_parts[0].strip()
                    if not phase.lower().startswith("phase") and not phase.isdigit():
                        feature = args.strip()
                        phase = ""
                elif feature:
                    pass
                if not feature:
                    return {"response": "Usage: /design <feature description> or /design phase 31: <feature>", "dag": None, "results": None}
                import uuid as _uuid_design
                design_id = _uuid_design.uuid4().hex[:12]
                _track_task(_run_design(
                    DesignRequest(feature=feature, phase=phase),
                    design_id,
                    runtime,
                ), name=f"design-{design_id}")
                return {
                    "response": f"Design request submitted (id: {design_id}). The Architect is analyzing...",
                    "design_id": design_id,
                    "dag": None,
                    "results": None,
                }
            return await _handle_slash_command(text, runtime)

        # AD-397/BF-009: @callsign direct message routing
        from probos.crew_profile import extract_callsign_mention
        mention = extract_callsign_mention(text)
        if mention:
            callsign, message_text = mention
            resolved = runtime.callsign_registry.resolve(callsign)
            if resolved is not None:
                if resolved["agent_id"] is None:
                    return {
                        "response": f"{resolved['callsign']} is not currently on duty.",
                        "dag": None,
                        "results": None,
                    }
                if not message_text:
                    return {
                        "response": f"{resolved['callsign']} is available. Send a message: @{callsign} <message>",
                        "dag": None,
                        "results": None,
                    }
                from probos.types import IntentMessage
                intent = IntentMessage(
                    intent="direct_message",
                    params={"text": message_text, "from": "hxi", "session": False},
                    target_agent_id=resolved["agent_id"],
                )
                result = await runtime.intent_bus.send(intent)
                response = f"{resolved['callsign']}: {result.result}" if result and result.result else f"{resolved['callsign']}: (no response)"
                return {"response": response, "dag": None, "results": None}
            # Callsign not found — fall through to NL processing

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

        try:
            dag_result = await asyncio.wait_for(
                runtime.process_natural_language(
                    req.message,
                    on_event=on_event,
                    auto_selfmod=False,
                    conversation_history=[(m.role, m.text) for m in req.history[-10:]],
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Chat request timed out after 30s: %s", req.message[:80])
            return {
                "response": "(Request timed out — the mesh took too long to respond. Try a simpler query.)",
                "dag": None,
                "results": None,
            }

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

        # Use shared response extraction for reflection/correction/results fallback
        if not response_text:
            from probos.utils.response_formatter import extract_response_text
            response_text = extract_response_text(dag_result)

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

        # Check for self-mod proposal (capability gap detected, API mode)
        self_mod = dag_result.get("self_mod")
        self_mod_proposal: dict[str, Any] | None = None
        if self_mod and self_mod.get("status") == "proposed":
            self_mod_proposal = {
                "intent_name": self_mod.get("intent", ""),
                "intent_description": self_mod.get("description", ""),
                "parameters": self_mod.get("parameters", {}),
                "original_message": req.message,
                "status": "proposed",
            }
            if not response_text or response_text.startswith("("):
                response_text = (
                    f"I don't have a capability for "
                    f"'{self_mod.get('intent', 'this')}' yet, "
                    f"but I can build one."
                )

        result_payload: dict[str, Any] = {
            "response": response_text,
            "dag": dag_dict,
            "results": results_dict,
        }
        if self_mod_proposal:
            result_payload["self_mod_proposal"] = self_mod_proposal
        return result_payload

    # ------------------------------------------------------------------
    # Self-mod approval endpoint (async pipeline)
    # ------------------------------------------------------------------

    @app.post("/api/selfmod/approve")
    async def approve_selfmod(req: SelfModRequest) -> dict[str, Any]:
        """Start async self-mod pipeline. Progress via WebSocket events."""
        if not getattr(runtime, 'self_mod_pipeline', None):
            return {"response": "Self-modification is not enabled.", "status": "error"}

        _track_task(_run_selfmod(req, runtime), name="selfmod")

        return {
            "response": "Starting agent design...",
            "status": "started",
        }

    @app.post("/api/selfmod/enrich")
    async def enrich_selfmod(req: EnrichRequest) -> dict[str, Any]:
        """Enrich a rough agent description into a detailed implementation spec."""
        if not getattr(runtime, 'llm_client', None):
            return {"enriched": req.user_guidance, "status": "no_llm"}

        from probos.types import LLMRequest

        enrich_prompt = (
            f"A user wants to create a new ProbOS agent. They provided this guidance:\n\n"
            f"Intent name: {req.intent_name}\n"
            f"Basic description: {req.intent_description}\n"
            f"Parameters: {req.parameters}\n"
            f"User's guidance: {req.user_guidance}\n\n"
            f"Expand this into a detailed, specific implementation plan for the agent. Include:\n"
            f"1. Exactly which URLs/APIs to use (prefer free, no-auth sources like DuckDuckGo)\n"
            f"2. How to parse the response data\n"
            f"3. What output format to return\n"
            f"4. Error handling approach\n"
            f"5. Any important constraints or limitations\n\n"
            f"Write this as a clear, concise specification (3-5 bullet points). "
            f"This will be given to an AI code generator to build the agent."
        )

        try:
            response = await runtime.llm_client.complete(LLMRequest(
                prompt=enrich_prompt,
                system_prompt=(
                    "You are a technical architect helping design an AI agent. "
                    "Produce a clear, actionable implementation spec from the user's rough description. "
                    "Be specific about data sources, parsing strategies, and output format. "
                    "Keep it concise — 3-5 bullet points. No code, just the spec."
                ),
                tier="fast",
                max_tokens=400,
            ))
            enriched = response.content.strip() if response and response.content else req.user_guidance
        except Exception:
            enriched = req.user_guidance

        return {
            "enriched": enriched,
            "intent_name": req.intent_name,
            "intent_description": req.intent_description,
            "parameters": req.parameters,
            "status": "ok",
        }

    async def _run_selfmod(
        req: SelfModRequest,
        rt: Any,
    ) -> None:
        """Background self-mod pipeline with WebSocket progress events."""
        original_approval_fn = None
        original_import_approval_fn = None
        try:
            rt._emit_event("self_mod_started", {
                "intent": req.intent_name,
                "description": req.intent_description,
                "message": f"Designing agent for '{req.intent_name}'...",
            })

            # Auto-approve imports in API mode — user already clicked Build Agent
            async def _auto_approve_imports(names: list[str]) -> bool:
                rt._emit_event("self_mod_import_approved", {
                    "intent": req.intent_name,
                    "imports": names,
                    "message": f"Added to allowed imports: {', '.join(names)}",
                })
                return True

            if rt.self_mod_pipeline:
                original_import_approval_fn = rt.self_mod_pipeline._import_approval_fn
                rt.self_mod_pipeline._import_approval_fn = _auto_approve_imports
                # Clicking "Build Agent" in the HXI IS the user's approval —
                # skip the console input() prompt that the Shell wires up.
                original_approval_fn = rt.self_mod_pipeline._user_approval_fn
                rt.self_mod_pipeline._user_approval_fn = None

            # Build execution context from prior execution
            exec_context = ""
            if rt._last_execution and rt._was_last_execution_successful():
                exec_context = rt._format_execution_context()

            async def _on_progress(step: str, current: int, total: int) -> None:
                step_labels = {
                    "designing": "\u2b21 Designing agent code...",
                    "validating": "\u25ce Validating & security scan...",
                    "testing": "\u25b3 Sandbox testing...",
                    "deploying": "\u25c8 Deploying to mesh...",
                }
                rt._emit_event("self_mod_progress", {
                    "intent": req.intent_name,
                    "step": step,
                    "step_label": step_labels.get(step, step),
                    "current": current,
                    "total": total,
                    "message": step_labels.get(step, f"Step {current}/{total}: {step}"),
                })

            record = await rt.self_mod_pipeline.handle_unhandled_intent(
                intent_name=req.intent_name,
                intent_description=req.intent_description,
                parameters=req.parameters,
                execution_context=exec_context,
                on_progress=_on_progress,
            )

            if record and record.status == "active":
                # Post-creation work
                knowledge_stored = False
                if rt._knowledge_store:
                    try:
                        await rt._knowledge_store.store_agent(record, record.source_code)
                        knowledge_stored = True
                    except Exception:
                        logger.warning(
                            "Failed to store agent '%s' in knowledge store",
                            record.agent_type, exc_info=True,
                        )
                semantic_indexed = False
                if rt._semantic_layer:
                    try:
                        await rt._semantic_layer.index_agent(
                            agent_type=record.agent_type,
                            intent_name=record.intent_name,
                            description=record.intent_name,
                            strategy=record.strategy,
                            source_snippet=record.source_code[:200] if record.source_code else "",
                        )
                        semantic_indexed = True
                    except Exception:
                        logger.warning(
                            "Failed to index agent '%s' in semantic layer",
                            record.agent_type, exc_info=True,
                        )

                # Generate capability report from designed agent source
                capability_report = ""
                try:
                    import ast as _ast
                    tree = _ast.parse(record.source_code)
                    instructions_value = ""
                    for node in _ast.walk(tree):
                        if isinstance(node, _ast.Assign):
                            for target in node.targets:
                                if isinstance(target, _ast.Name) and target.id == "instructions":
                                    if isinstance(node.value, (_ast.Constant, _ast.Str)):
                                        instructions_value = getattr(node.value, 'value', '') or getattr(node.value, 's', '')
                                    elif isinstance(node.value, _ast.JoinedStr):
                                        instructions_value = "(f-string instructions)"

                    if instructions_value and hasattr(rt, 'llm_client'):
                        from probos.types import LLMRequest
                        report_prompt = (
                            f"A new ProbOS agent was just created. Summarize what it does in 2-3 sentences "
                            f"for a non-technical audience. Be specific about its capabilities.\n\n"
                            f"Agent name: {record.class_name}\n"
                            f"Intent: {record.intent_name}\n"
                            f"Description: {req.intent_description}\n"
                            f"Agent instructions: {instructions_value[:500]}\n"
                        )
                        report_response = await rt.llm_client.complete(LLMRequest(
                            prompt=report_prompt,
                            system_prompt="You are a technical writer. Write a brief, impressive summary of a new AI agent's capabilities. Use bullet points. Keep it under 100 words.",
                            tier="fast",
                            max_tokens=256,
                        ))
                        if report_response and report_response.content:
                            capability_report = report_response.content.strip()
                except Exception:
                    logger.debug("Capability report generation failed", exc_info=True)

                deploy_msg = f"\u2b22 {record.class_name} deployed!"
                if capability_report:
                    deploy_msg += f"\n\n{capability_report}\n\nHandling your request..."
                else:
                    deploy_msg += " Handling your request..."

                # Build warnings for partial failures
                warnings = []
                if not knowledge_stored:
                    warnings.append("knowledge store indexing failed")
                if not semantic_indexed:
                    warnings.append("semantic layer indexing failed")

                success_msg = deploy_msg
                if warnings:
                    success_msg += f" (warnings: {', '.join(warnings)})"

                rt._emit_event("self_mod_success", {
                    "intent": req.intent_name,
                    "agent_type": record.agent_type,
                    "agent_id": record.agent_id if hasattr(record, 'agent_id') else record.agent_type,
                    "message": success_msg,
                    "warnings": warnings,
                })

                # Auto-retry the original request
                if req.original_message:
                    rt._emit_event("self_mod_progress", {
                        "intent": req.intent_name,
                        "step": "executing",
                        "step_label": "\u26ac Executing your request...",
                        "current": 5,
                        "total": 5,
                        "message": "\u26ac Executing your request...",
                    })
                    try:
                        # Use the intent description for retry, not the original meta-request.
                        # "I want you to design an agent that can X" should retry as just "X"
                        retry_message = req.intent_description or req.original_message
                        result = await rt.process_natural_language(retry_message)
                        response = (
                            result.get("response", "")
                            or result.get("reflection", "")
                            or "Done."
                        )
                        rt._emit_event("self_mod_retry_complete", {
                            "intent": req.intent_name,
                            "response": response,
                            "message": response,
                        })
                    except Exception as retry_err:
                        logger.warning("Self-mod retry failed: %s", retry_err)
                        rt._emit_event("self_mod_retry_complete", {
                            "intent": req.intent_name,
                            "message": f"Agent deployed but retry failed: {retry_err}",
                        })

                # QA after user gets their result — don't compete for rate limiter
                if rt._system_qa is not None:
                    asyncio.create_task(rt._run_qa_for_designed_agent(record))
            else:
                error_detail = getattr(record, 'error', '') if record else "design returned no result"
                status = getattr(record, 'status', 'unknown') if record else "failed"
                logger.warning("Self-mod failed for %s: status=%s error=%s", req.intent_name, status, error_detail)
                rt._emit_event("self_mod_failure", {
                    "intent": req.intent_name,
                    "message": f"Agent design failed: {error_detail or status}",
                    "error": error_detail or status,
                })
        except Exception as e:
            logger.warning("Self-mod pipeline failed: %s", e, exc_info=True)
            rt._emit_event("self_mod_failure", {
                "intent": req.intent_name,
                "message": f"Agent design failed: {e}",
            })
        finally:
            # Restore callbacks for interactive shell use
            if rt.self_mod_pipeline:
                if original_approval_fn is not None:
                    rt.self_mod_pipeline._user_approval_fn = original_approval_fn
                if original_import_approval_fn is not None:
                    rt.self_mod_pipeline._import_approval_fn = original_import_approval_fn

    # ------------------------------------------------------------------
    # Builder Agent API (AD-304)
    # ------------------------------------------------------------------

    @app.post("/api/build/submit")
    async def submit_build(req: BuildRequest) -> dict[str, Any]:
        """Start async build generation. Progress via WebSocket events."""
        import uuid
        build_id = uuid.uuid4().hex[:12]

        _track_task(_run_build(req, build_id, runtime), name=f"build-{build_id}")

        return {
            "status": "started",
            "build_id": build_id,
            "message": f"Build '{req.title}' started...",
        }

    @app.post("/api/build/approve")
    async def approve_build(req: BuildApproveRequest) -> dict[str, Any]:
        """Execute an approved build — write files, test, commit."""
        from probos.cognitive.builder import BuildSpec, execute_approved_build
        import pathlib

        spec = BuildSpec(
            title=req.title,
            description=req.description,
            ad_number=req.ad_number,
            branch_name=req.branch_name,
        )

        work_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent)

        _track_task(
            _execute_build(req.build_id, req.file_changes, spec, work_dir, runtime),
            name=f"execute-{req.build_id}",
        )

        return {
            "status": "started",
            "build_id": req.build_id,
            "message": "Executing approved build...",
        }

    @app.post("/api/build/resolve")
    async def resolve_build(req: BuildResolveRequest) -> dict[str, Any]:
        """Execute a resolution option for a failed build (AD-345)."""
        _clean_expired_failures()

        if req.build_id not in _pending_failures:
            return {"status": "error", "message": "Build not found or expired. Re-run the build."}

        cached = _pending_failures[req.build_id]
        file_changes = cached["file_changes"]
        spec = cached["spec"]
        work_dir = cached["work_dir"]

        if req.resolution == "abort":
            from probos.cognitive.builder import _git_checkout_main
            await _git_checkout_main(work_dir)
            del _pending_failures[req.build_id]
            runtime._emit_event("build_resolved", {
                "build_id": req.build_id,
                "resolution": "abort",
                "message": "Build aborted. Returned to main branch.",
            })
            return {"status": "ok", "resolution": "abort"}

        elif req.resolution == "commit_override":
            from probos.cognitive.builder import _git_add_and_commit
            report = cached["report"]
            all_files = report.files_written + report.files_modified
            if not all_files:
                return {"status": "error", "message": "No files to commit."}
            commit_msg = (
                f"{spec.title}"
                + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                + "\n\n[Test gate overridden by Captain]"
                + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
            )
            ok, sha = await _git_add_and_commit(all_files, commit_msg, work_dir)
            del _pending_failures[req.build_id]
            if ok:
                runtime._emit_event("build_resolved", {
                    "build_id": req.build_id,
                    "resolution": "commit_override",
                    "message": f"Committed with test gate override. Commit: {sha}",
                    "commit": sha,
                })
                return {"status": "ok", "resolution": "commit_override", "commit": sha}
            else:
                return {"status": "error", "message": f"Commit failed: {sha}"}

        elif req.resolution in ("retry_extended", "retry_targeted", "retry_fix", "retry_full"):
            # Re-run build as background task
            del _pending_failures[req.build_id]
            new_build_id = req.build_id  # Reuse same build_id for continuity

            runtime._emit_event("build_progress", {
                "build_id": new_build_id,
                "step": "retrying",
                "step_label": "\u25c8 Retrying build...",
                "current": 1,
                "total": 3,
                "message": f"\u25c8 Resolution: {req.resolution}",
            })

            _track_task(
                _execute_build(new_build_id, file_changes, spec, work_dir, runtime),
                name=f"build-resolve-{new_build_id}",
            )
            return {"status": "ok", "resolution": req.resolution, "build_id": new_build_id}

        else:
            return {"status": "error", "message": f"Unknown resolution: {req.resolution}"}

    # ------------------------------------------------------------------
    # Build Queue / Dispatch API (AD-375)
    # ------------------------------------------------------------------

    def _emit_queue_snapshot(rt: Any) -> None:
        """Broadcast full queue state to all HXI clients (AD-375)."""
        if not rt.build_queue:
            return
        items = rt.build_queue.get_all()
        rt._emit_event("build_queue_update", {
            "items": [
                {
                    "id": b.id,
                    "title": b.spec.title,
                    "ad_number": b.spec.ad_number,
                    "status": b.status,
                    "priority": b.priority,
                    "worktree_path": b.worktree_path,
                    "builder_id": b.builder_id,
                    "error": b.error,
                    "file_footprint": b.file_footprint,
                    "commit_hash": b.result.commit_hash if b.result else "",
                }
                for b in items
            ],
        })

    @app.post("/api/build/queue/approve")
    async def approve_queued_build(req: BuildQueueApproveRequest) -> dict[str, Any]:
        """Captain approves a queued build — merge worktree to main."""
        if not runtime.build_dispatcher:
            return {"status": "error", "message": "Build dispatcher not running"}
        ok, result = await runtime.build_dispatcher.approve_and_merge(req.build_id)
        if ok:
            _emit_queue_snapshot(runtime)
            return {"status": "ok", "commit": result, "message": f"Build merged: {result[:7]}"}
        return {"status": "error", "message": result}

    @app.post("/api/build/queue/reject")
    async def reject_queued_build(req: BuildQueueRejectRequest) -> dict[str, Any]:
        """Captain rejects a queued build — discard worktree."""
        if not runtime.build_dispatcher:
            return {"status": "error", "message": "Build dispatcher not running"}
        ok = await runtime.build_dispatcher.reject_build(req.build_id)
        if ok:
            _emit_queue_snapshot(runtime)
            return {"status": "ok", "message": "Build rejected"}
        return {"status": "error", "message": f"Build {req.build_id} not in reviewing status"}

    @app.post("/api/build/enqueue")
    async def enqueue_build(req: BuildEnqueueRequest) -> dict[str, Any]:
        """Add a build spec to the dispatch queue."""
        if not runtime.build_queue:
            return {"status": "error", "message": "Build queue not running"}
        from probos.cognitive.builder import BuildSpec
        spec = BuildSpec(
            title=req.title,
            description=req.description,
            target_files=req.target_files,
            reference_files=req.reference_files,
            test_files=req.test_files,
            ad_number=req.ad_number,
            constraints=req.constraints,
        )
        build = runtime.build_queue.enqueue(spec, priority=req.priority)
        _emit_queue_snapshot(runtime)
        return {
            "status": "ok",
            "build_id": build.id,
            "message": f"Build '{req.title}' queued at priority {req.priority}",
        }

    @app.get("/api/build/queue")
    async def get_build_queue() -> dict[str, Any]:
        """Get the current build queue state."""
        if not runtime.build_queue:
            return {"status": "ok", "items": []}
        items = runtime.build_queue.get_all()
        return {
            "status": "ok",
            "items": [
                {
                    "id": b.id,
                    "title": b.spec.title,
                    "ad_number": b.spec.ad_number,
                    "status": b.status,
                    "priority": b.priority,
                    "worktree_path": b.worktree_path,
                    "builder_id": b.builder_id,
                    "error": b.error,
                    "file_footprint": b.file_footprint,
                    "commit_hash": b.result.commit_hash if b.result else "",
                }
                for b in items
            ],
            "active_count": runtime.build_queue.active_count,
        }

    @app.post("/api/notifications/{notification_id}/ack")
    async def ack_notification(notification_id: str) -> dict[str, Any]:
        """Acknowledge a single notification (AD-323)."""
        ok = runtime.notification_queue.acknowledge(notification_id)
        return {"acknowledged": ok}

    @app.post("/api/notifications/ack-all")
    async def ack_all_notifications() -> dict[str, Any]:
        """Acknowledge all unread notifications (AD-323)."""
        count = runtime.notification_queue.acknowledge_all()
        return {"acknowledged": count}

    # ---------- Agent Profile Panel (AD-406) ----------

    @app.get("/api/agent/{agent_id}/profile")
    async def agent_profile(agent_id: str) -> dict[str, Any]:
        """Get detailed profile for a specific agent."""
        agent = runtime.registry.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Basic info
        callsign = ""
        department = ""
        rank = "ensign"
        display_name = ""
        personality: dict[str, float] = {}
        specialization: list[str] = []

        # Crew profile from YAML seed data
        if hasattr(runtime, 'callsign_registry'):
            callsign = runtime.callsign_registry.get_callsign(agent.agent_type)
            resolved = runtime.callsign_registry.resolve(callsign) if callsign else None
            if resolved:
                department = resolved.get("department", "")
                display_name = resolved.get("display_name", "")

        # Load full seed profile for personality
        from probos.crew_profile import load_seed_profile, Rank
        seed = load_seed_profile(agent.agent_type)
        if seed:
            personality = seed.get("personality", {})
            specialization = seed.get("specialization", [])
            display_name = display_name or seed.get("display_name", "")
            department = department or seed.get("department", "")

        # Trust
        trust_score = 0.5
        trust_history: list[float] = []
        if hasattr(runtime, 'trust_network'):
            trust_score = runtime.trust_network.get_score(agent.id)
            rank = Rank.from_trust(trust_score).value
            from probos.earned_agency import agency_from_rank
            agency_level = agency_from_rank(Rank.from_trust(trust_score)).value
            # Get recent trust history if available
            if hasattr(runtime.trust_network, 'get_history'):
                trust_history = runtime.trust_network.get_history(agent.id, limit=20)

        # Hebbian connections
        hebbian_connections: list[dict[str, Any]] = []
        if hasattr(runtime, 'hebbian_router'):
            for (source, target, rel_type), weight in runtime.hebbian_router.all_weights_typed().items():
                if source == agent.id or target == agent.id:
                    other_id = target if source == agent.id else source
                    hebbian_connections.append({
                        "targetId": other_id,
                        "weight": round(weight, 4),
                        "relType": rel_type,
                    })
            # Sort by weight descending, limit to top 10
            hebbian_connections.sort(key=lambda c: c["weight"], reverse=True)
            hebbian_connections = hebbian_connections[:10]

        # Memory count
        memory_count = 0
        if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
            if hasattr(runtime.episodic_memory, 'count_for_agent'):
                memory_count = await runtime.episodic_memory.count_for_agent(agent.id)

        # BF-017: Only crew agents get personality and proactive controls
        is_crew = runtime._is_crew_agent(agent)

        return {
            "id": agent.id,
            "sovereignId": getattr(agent, 'sovereign_id', ''),
            "did": getattr(agent, 'did', ''),
            "agentType": agent.agent_type,
            "callsign": callsign,
            "displayName": display_name,
            "rank": rank,
            "agencyLevel": agency_level,
            "department": department,
            "personality": personality if is_crew else {},
            "specialization": specialization,
            "trust": round(trust_score, 4),
            "trustHistory": trust_history,
            "confidence": round(agent.confidence, 4),
            "state": agent.state.value if hasattr(agent.state, 'value') else str(agent.state),
            "tier": agent.tier if hasattr(agent, 'tier') else "domain",
            "pool": agent.pool,
            "hebbianConnections": hebbian_connections,
            "memoryCount": memory_count,
            "uptime": round(time.monotonic() - runtime._start_time, 1),
            "isCrew": is_crew,
            "proactiveCooldown": runtime.proactive_loop.get_agent_cooldown(agent.id) if is_crew and hasattr(runtime, 'proactive_loop') and runtime.proactive_loop else None,
        }

    @app.put("/api/agent/{agent_id}/proactive-cooldown")
    async def set_agent_proactive_cooldown(agent_id: str, req: dict) -> dict[str, Any]:
        """Set per-agent proactive cooldown (seconds). Range: 60-1800."""
        agent = runtime.registry.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        # BF-017: Only crew agents have proactive thinking
        if not runtime._is_crew_agent(agent):
            raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent")
        cooldown = float(req.get("cooldown", 300))
        if hasattr(runtime, 'proactive_loop') and runtime.proactive_loop:
            runtime.proactive_loop.set_agent_cooldown(agent_id, cooldown)
        return {"agentId": agent_id, "cooldown": runtime.proactive_loop.get_agent_cooldown(agent_id) if runtime.proactive_loop else 300.0}

    @app.post("/api/agent/{agent_id}/chat")
    async def agent_chat(agent_id: str, req: AgentChatRequest) -> dict[str, Any]:
        """Send a direct message to a specific agent and get their response."""
        agent = runtime.registry.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        # BF-017: Only crew agents support direct chat
        if not runtime._is_crew_agent(agent):
            raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent — direct chat is crew-only")

        from probos.types import IntentMessage
        intent = IntentMessage(
            intent="direct_message",
            params={
                "text": req.message,
                "from": "hxi_profile",
                "session": bool(req.history),  # AD-430b: session=True when history present
                "session_history": req.history[-10:] if req.history else [],  # AD-430b: last 10 exchanges
            },
            target_agent_id=agent_id,
        )
        result = await runtime.intent_bus.send(intent)

        callsign = ""
        if hasattr(runtime, 'callsign_registry'):
            callsign = runtime.callsign_registry.get_callsign(agent.agent_type)

        response_text = ""
        if result and result.result:
            response_text = str(result.result)
        elif result and result.error:
            response_text = f"(error: {result.error})"
        else:
            response_text = "(no response)"

        # AD-430b: Store HXI 1:1 interaction as episodic memory
        if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
            try:
                import time as _time
                from probos.types import Episode
                episode = Episode(
                    user_input=f"[1:1 with {callsign or agent_id}] Captain: {req.message}",
                    timestamp=_time.time(),
                    agent_ids=[agent_id],
                    outcomes=[{
                        "intent": "direct_message",
                        "success": True,
                        "response": response_text[:500],
                        "session_type": "1:1",
                        "callsign": callsign,
                        "source": "hxi_profile",
                        "agent_type": agent.agent_type,
                    }],
                    reflection=f"Captain had a 1:1 conversation with {callsign or agent_id} via HXI.",
                )
                await runtime.episodic_memory.store(episode)
            except Exception:
                pass  # Non-critical — don't block the response

        return {
            "response": response_text,
            "callsign": callsign,
            "agentId": agent_id,
        }

    @app.get("/api/agent/{agent_id}/chat/history")
    async def agent_chat_history(agent_id: str) -> dict[str, Any]:
        """Recall past 1:1 interactions with this agent for session seeding."""
        memories: list[dict[str, str]] = []
        if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
            try:
                episodes = await runtime.episodic_memory.recall_for_agent(
                    agent_id, "1:1 conversation with Captain", k=3
                )
                # BF-028: Fallback to recent episodes when semantic recall misses
                if not episodes and hasattr(runtime.episodic_memory, 'recent_for_agent'):
                    episodes = await runtime.episodic_memory.recent_for_agent(
                        agent_id, k=3
                    )
                for ep in episodes:
                    memories.append({
                        "role": "system",
                        "text": f"[Previous conversation] {ep.user_input}",
                    })
            except Exception:
                pass
        return {"memories": memories}

    # --- Cognitive Journal (AD-431) ---

    @app.get("/api/journal/stats")
    async def journal_stats() -> dict[str, Any]:
        """AD-431: Cognitive Journal statistics."""
        if not runtime.cognitive_journal:
            return {"total_entries": 0}
        return await runtime.cognitive_journal.get_stats()

    @app.get("/api/agent/{agent_id}/journal")
    async def agent_journal(
        agent_id: str, limit: int = 20,
        since: float | None = None, until: float | None = None,
    ) -> dict[str, Any]:
        """AD-431: Agent reasoning chain from Cognitive Journal."""
        if not runtime.cognitive_journal:
            return {"entries": []}
        entries = await runtime.cognitive_journal.get_reasoning_chain(
            agent_id, limit=min(limit, 100), since=since, until=until,
        )
        return {"agent_id": agent_id, "entries": entries}

    @app.get("/api/journal/tokens")
    async def journal_token_usage(agent_id: str | None = None) -> dict[str, Any]:
        """AD-431: Token usage summary (ship-wide or per-agent)."""
        if not runtime.cognitive_journal:
            return {"total_tokens": 0, "total_calls": 0}
        return await runtime.cognitive_journal.get_token_usage(agent_id)

    @app.get("/api/journal/tokens/by")
    async def journal_token_usage_by(
        group_by: str = "model", agent_id: str | None = None,
    ) -> dict[str, Any]:
        """AD-432: Token usage grouped by model, tier, agent, or intent."""
        if not runtime.cognitive_journal:
            return {"groups": []}
        groups = await runtime.cognitive_journal.get_token_usage_by(
            group_by=group_by, agent_id=agent_id,
        )
        return {"group_by": group_by, "groups": groups}

    @app.get("/api/journal/decisions")
    async def journal_decision_points(
        agent_id: str | None = None,
        min_latency_ms: float | None = None,
        failures_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """AD-432: Notable decision points — high-latency or failed LLM calls."""
        if not runtime.cognitive_journal:
            return {"entries": []}
        entries = await runtime.cognitive_journal.get_decision_points(
            agent_id=agent_id,
            min_latency_ms=min_latency_ms,
            failures_only=failures_only,
            limit=min(limit, 100),
        )
        return {"entries": entries}

    # --- Ward Room (AD-407) ---

    @app.get("/api/wardroom/channels")
    async def wardroom_channels():
        if not runtime.ward_room:
            return {"channels": []}
        channels = await runtime.ward_room.list_channels()
        return {"channels": [vars(c) for c in channels]}

    @app.post("/api/wardroom/channels")
    async def wardroom_create_channel(req: CreateChannelRequest):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        try:
            ch = await runtime.ward_room.create_channel(
                name=req.name, channel_type="custom",
                created_by=req.created_by, description=req.description,
            )
            return vars(ch)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/wardroom/channels/{channel_id}/threads")
    async def wardroom_threads(channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent"):
        if not runtime.ward_room:
            return {"threads": []}
        threads = await runtime.ward_room.list_threads(channel_id, limit=limit, offset=offset, sort=sort)
        return {"threads": [vars(t) for t in threads]}

    @app.post("/api/wardroom/channels/{channel_id}/threads")
    async def wardroom_create_thread(channel_id: str, req: CreateThreadRequest):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        try:
            thread = await runtime.ward_room.create_thread(
                channel_id=channel_id, author_id=req.author_id,
                title=req.title, body=req.body,
                author_callsign=req.author_callsign,
                thread_mode=req.thread_mode,
                max_responders=req.max_responders,
            )
            return vars(thread)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/wardroom/threads/{thread_id}")
    async def wardroom_thread_detail(thread_id: str):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        result = await runtime.ward_room.get_thread(thread_id)
        if not result:
            raise HTTPException(404, "Thread not found")
        return result

    @app.patch("/api/wardroom/threads/{thread_id}")
    async def wardroom_update_thread(thread_id: str, req: UpdateThreadRequest):
        """AD-424: Update thread properties (Captain-level)."""
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        updates = req.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(400, "No updates provided")
        thread = await runtime.ward_room.update_thread(thread_id, **updates)
        if not thread:
            raise HTTPException(404, "Thread not found")
        return vars(thread)

    @app.post("/api/wardroom/threads/{thread_id}/posts")
    async def wardroom_create_post(thread_id: str, req: CreatePostRequest):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        try:
            post = await runtime.ward_room.create_post(
                thread_id=thread_id, author_id=req.author_id,
                body=req.body, parent_id=req.parent_id,
                author_callsign=req.author_callsign,
            )
            return vars(post)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/wardroom/posts/{post_id}/endorse")
    async def wardroom_endorse(post_id: str, req: EndorseRequest):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        try:
            result = await runtime.ward_room.endorse(
                target_id=post_id, target_type="post",
                voter_id=req.voter_id, direction=req.direction,
            )
            return result
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/wardroom/threads/{thread_id}/endorse")
    async def wardroom_endorse_thread(thread_id: str, req: EndorseRequest):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        try:
            result = await runtime.ward_room.endorse(
                target_id=thread_id, target_type="thread",
                voter_id=req.voter_id, direction=req.direction,
            )
            return result
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/wardroom/channels/{channel_id}/subscribe")
    async def wardroom_subscribe(channel_id: str, req: SubscribeRequest):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        if req.action == "unsubscribe":
            await runtime.ward_room.unsubscribe(req.agent_id, channel_id)
        else:
            await runtime.ward_room.subscribe(req.agent_id, channel_id)
        return {"ok": True}

    @app.get("/api/wardroom/agent/{agent_id}/credibility")
    async def wardroom_credibility(agent_id: str):
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        cred = await runtime.ward_room.get_credibility(agent_id)
        result = vars(cred)
        result["restrictions"] = list(cred.restrictions)
        return result

    @app.get("/api/wardroom/notifications")
    async def wardroom_notifications(agent_id: str):
        if not runtime.ward_room:
            return {"unread": {}}
        counts = await runtime.ward_room.get_unread_counts(agent_id)
        return {"unread": counts}

    # AD-425: Activity feed — cross-channel browsing
    @app.get("/api/wardroom/activity")
    async def wardroom_activity_feed(
        agent_id: str | None = None,
        channel_id: str | None = None,
        thread_mode: str | None = None,
        limit: int = 20,
        since: float = 0.0,
        sort: str = "recent",      # AD-426: "recent" or "top"
    ):
        """Browse Ward Room threads across channels."""
        if not runtime.ward_room:
            return {"threads": []}
        if channel_id:
            threads = await runtime.ward_room.list_threads(channel_id, limit=limit, sort=sort)
            # Apply optional filters
            if thread_mode:
                threads = [t for t in threads if t.thread_mode == thread_mode]
            if since > 0:
                threads = [t for t in threads if t.last_activity > since]
        elif agent_id:
            threads = await runtime.ward_room.browse_threads(
                agent_id, thread_mode=thread_mode, limit=limit, since=since,
                sort=sort,
            )
        else:
            # Captain view — browse all channels
            all_channels = await runtime.ward_room.list_channels()
            all_ch_ids = [c.id for c in all_channels]
            threads = await runtime.ward_room.browse_threads(
                "_anonymous", channels=all_ch_ids,
                thread_mode=thread_mode, limit=limit, since=since,
                sort=sort,
            )
        return {"threads": [vars(t) for t in threads]}

    @app.put("/api/wardroom/channels/{channel_id}/seen")
    async def wardroom_mark_seen(channel_id: str, agent_id: str):
        """Mark all threads in a channel as seen for an agent."""
        if not runtime.ward_room:
            raise HTTPException(503, "Ward Room not available")
        await runtime.ward_room.update_last_seen(agent_id, channel_id)
        return {"status": "ok"}

    @app.get("/api/wardroom/proposals")
    async def list_improvement_proposals(
        status: str | None = None, limit: int = 20,
    ) -> dict[str, Any]:
        """AD-412: List improvement proposals from the #Improvement Proposals channel."""
        if not runtime.ward_room:
            return {"proposals": []}

        # Find the Improvement Proposals channel
        channels = await runtime.ward_room.list_channels()
        proposals_ch = None
        for ch in channels:
            if ch.name == "Improvement Proposals":
                proposals_ch = ch
                break

        if not proposals_ch:
            return {"proposals": []}

        threads = await runtime.ward_room.list_threads(
            proposals_ch.id, limit=min(limit, 100),
        )

        proposals = []
        for t in threads:
            proposal = {
                "thread_id": t.id,
                "title": t.title,
                "body": t.body,
                "author": t.author_callsign or t.author_id,
                "created_at": t.created_at,
                "net_score": t.net_score,
                "reply_count": t.reply_count,
                "status": "approved" if t.net_score > 0 else "shelved" if t.net_score < 0 else "pending",
            }
            proposals.append(proposal)

        # Optional status filter
        if status:
            proposals = [p for p in proposals if p["status"] == status]

        return {"channel_id": proposals_ch.id, "proposals": proposals}

    # AD-416: Ward Room stats & manual prune
    @app.get("/api/ward-room/stats")
    async def ward_room_stats():
        if not runtime.ward_room:
            return JSONResponse({"error": "Ward Room not enabled"}, status_code=503)
        stats = await runtime.ward_room.get_stats()
        config = runtime.config.ward_room
        pruneable = await runtime.ward_room.count_pruneable(
            config.retention_days, config.retention_days_endorsed, config.retention_days_captain,
        )
        stats["pruneable_threads"] = pruneable
        stats["retention_days"] = config.retention_days
        stats["retention_days_endorsed"] = config.retention_days_endorsed
        return stats

    @app.post("/api/ward-room/prune")
    async def ward_room_prune():
        if not runtime.ward_room:
            return JSONResponse({"error": "Ward Room not enabled"}, status_code=503)
        config = runtime.config.ward_room
        archive_path = None
        if config.archive_enabled:
            archive_dir = runtime._data_dir / "ward_room_archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            month = datetime.now().strftime("%Y-%m")
            archive_path = str(archive_dir / f"ward_room_archive_{month}.jsonl")
        result = await runtime.ward_room.prune_old_threads(
            retention_days=config.retention_days,
            retention_days_endorsed=config.retention_days_endorsed,
            retention_days_captain=config.retention_days_captain,
            archive_path=archive_path,
        )
        # Don't expose internal pruned_thread_ids list
        result.pop("pruned_thread_ids", None)
        return result

    # --- Skill Framework (AD-428) ---

    @app.get("/api/skills/registry")
    async def skills_registry(
        category: str | None = None, domain: str | None = None,
    ) -> dict[str, Any]:
        """List all skill definitions in the registry."""
        if not runtime.skill_registry:
            return {"skills": []}
        from probos.skill_framework import SkillCategory
        cat = SkillCategory(category) if category else None
        skills = runtime.skill_registry.list_skills(category=cat, domain=domain)
        return {"skills": [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "category": s.category.value,
                "description": s.description,
                "domain": s.domain,
                "prerequisites": s.prerequisites,
                "decay_rate_days": s.decay_rate_days,
                "origin": s.origin,
            }
            for s in skills
        ]}

    @app.get("/api/skills/agents/{agent_id}/profile")
    async def skill_profile(agent_id: str) -> dict[str, Any]:
        """Get the full skill profile for an agent."""
        if not runtime.skill_service:
            return {"agent_id": agent_id, "pccs": [], "role_skills": [], "acquired_skills": [], "depth": 0, "breadth": 0}
        profile = await runtime.skill_service.get_profile(agent_id)
        return profile.to_dict()

    @app.post("/api/skills/agents/{agent_id}/commission")
    async def skill_commission(agent_id: str, req: SkillCommissionRequest) -> dict[str, Any]:
        """Commission an agent with initial PCC + role skills."""
        if not runtime.skill_service:
            raise HTTPException(503, "Skill service not available")
        profile = await runtime.skill_service.commission_agent(agent_id, req.agent_type)
        return profile.to_dict()

    @app.post("/api/skills/agents/{agent_id}/assess")
    async def skill_assess(agent_id: str, req: SkillAssessmentRequest) -> dict[str, Any]:
        """Record a skill assessment (update proficiency)."""
        if not runtime.skill_service:
            raise HTTPException(503, "Skill service not available")
        from probos.skill_framework import ProficiencyLevel
        try:
            level = ProficiencyLevel(req.new_level)
        except ValueError:
            raise HTTPException(400, f"Invalid proficiency level: {req.new_level}")
        record = await runtime.skill_service.update_proficiency(
            agent_id, req.skill_id, level, source=req.source, notes=req.notes,
        )
        if not record:
            raise HTTPException(404, f"Agent {agent_id} does not have skill {req.skill_id}")
        return record.to_dict()

    @app.post("/api/skills/agents/{agent_id}/exercise")
    async def skill_exercise(agent_id: str, skill_id: str) -> dict[str, Any]:
        """Record that an agent exercised a skill."""
        if not runtime.skill_service:
            raise HTTPException(503, "Skill service not available")
        record = await runtime.skill_service.record_exercise(agent_id, skill_id)
        if not record:
            raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
        return record.to_dict()

    @app.get("/api/skills/agents/{agent_id}/prerequisites/{skill_id}")
    async def skill_prerequisites(agent_id: str, skill_id: str) -> dict[str, Any]:
        """Check if an agent meets prerequisites for a skill."""
        if not runtime.skill_service:
            return {"met": True, "missing": []}
        return await runtime.skill_service.check_prerequisites(agent_id, skill_id)

    # --- Agent Capital Management (AD-427) ---

    @app.get("/api/acm/agents/{agent_id}/profile")
    async def get_acm_profile(agent_id: str) -> dict[str, Any]:
        """AD-427: Consolidated agent profile from ACM."""
        if not runtime.acm:
            return {"error": "ACM not available"}
        return await runtime.acm.get_consolidated_profile(agent_id, runtime)

    @app.get("/api/acm/agents/{agent_id}/lifecycle")
    async def get_acm_lifecycle(agent_id: str) -> dict[str, Any]:
        """AD-427: Agent lifecycle state and transition history."""
        if not runtime.acm:
            return {"error": "ACM not available"}
        state = await runtime.acm.get_lifecycle_state(agent_id)
        history = await runtime.acm.get_transition_history(agent_id)
        return {
            "agent_id": agent_id,
            "current_state": state.value,
            "transitions": [
                {
                    "from_state": t.from_state,
                    "to_state": t.to_state,
                    "reason": t.reason,
                    "initiated_by": t.initiated_by,
                    "timestamp": t.timestamp,
                }
                for t in history
            ],
        }

    @app.post("/api/acm/agents/{agent_id}/decommission")
    async def decommission_agent(agent_id: str, req: dict) -> dict[str, Any]:
        """AD-427: Decommission an agent."""
        if not runtime.acm:
            return {"error": "ACM not available"}
        reason = req.get("reason", "Decommissioned by Captain")
        try:
            t = await runtime.acm.decommission(agent_id, reason=reason, initiated_by="captain")
            return {"status": "decommissioned", "transition": {
                "from_state": t.from_state, "to_state": t.to_state,
                "reason": t.reason, "timestamp": t.timestamp,
            }}
        except ValueError as e:
            return {"error": str(e)}

    @app.post("/api/acm/agents/{agent_id}/suspend")
    async def suspend_agent(agent_id: str, req: dict) -> dict[str, Any]:
        """AD-427: Suspend an agent (Captain order)."""
        if not runtime.acm:
            return {"error": "ACM not available"}
        from probos.acm import LifecycleState
        reason = req.get("reason", "Suspended by Captain")
        try:
            t = await runtime.acm.transition(
                agent_id, LifecycleState.SUSPENDED,
                reason=reason, initiated_by="captain",
            )
            return {"status": "suspended", "transition": {
                "from_state": t.from_state, "to_state": t.to_state,
                "reason": t.reason, "timestamp": t.timestamp,
            }}
        except ValueError as e:
            return {"error": str(e)}

    @app.post("/api/acm/agents/{agent_id}/reinstate")
    async def reinstate_agent(agent_id: str, req: dict) -> dict[str, Any]:
        """AD-427: Reinstate a suspended agent."""
        if not runtime.acm:
            return {"error": "ACM not available"}
        from probos.acm import LifecycleState
        reason = req.get("reason", "Reinstated by Captain")
        try:
            t = await runtime.acm.transition(
                agent_id, LifecycleState.ACTIVE,
                reason=reason, initiated_by="captain",
            )
            return {"status": "active", "transition": {
                "from_state": t.from_state, "to_state": t.to_state,
                "reason": t.reason, "timestamp": t.timestamp,
            }}
        except ValueError as e:
            return {"error": str(e)}

    # --- Assignments (AD-408) ---

    @app.get("/api/assignments")
    async def list_assignments(status: str = "active"):
        if not runtime.assignment_service:
            return {"assignments": []}
        assignments = await runtime.assignment_service.list_assignments(status=status)
        return {"assignments": [vars(a) for a in assignments]}

    @app.post("/api/assignments")
    async def create_assignment(req: CreateAssignmentRequest):
        if not runtime.assignment_service:
            raise HTTPException(503, "Assignment service not available")
        try:
            assignment = await runtime.assignment_service.create_assignment(
                name=req.name,
                assignment_type=req.assignment_type,
                created_by=req.created_by,
                members=req.members,
                mission=req.mission,
            )
            return vars(assignment)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/assignments/{assignment_id}")
    async def get_assignment(assignment_id: str):
        if not runtime.assignment_service:
            raise HTTPException(503, "Assignment service not available")
        assignment = await runtime.assignment_service.get_assignment(assignment_id)
        if not assignment:
            raise HTTPException(404, "Assignment not found")
        return vars(assignment)

    @app.post("/api/assignments/{assignment_id}/members")
    async def modify_assignment_members(assignment_id: str, req: ModifyMembersRequest):
        if not runtime.assignment_service:
            raise HTTPException(503, "Assignment service not available")
        try:
            if req.action == "remove":
                assignment = await runtime.assignment_service.remove_member(assignment_id, req.agent_id)
            else:
                assignment = await runtime.assignment_service.add_member(assignment_id, req.agent_id)
            return vars(assignment)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/assignments/{assignment_id}/complete")
    async def complete_assignment(assignment_id: str):
        if not runtime.assignment_service:
            raise HTTPException(503, "Assignment service not available")
        try:
            assignment = await runtime.assignment_service.complete_assignment(assignment_id)
            return vars(assignment)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/assignments/{assignment_id}")
    async def dissolve_assignment(assignment_id: str):
        if not runtime.assignment_service:
            raise HTTPException(503, "Assignment service not available")
        try:
            assignment = await runtime.assignment_service.dissolve_assignment(assignment_id)
            return vars(assignment)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/assignments/agent/{agent_id}")
    async def agent_assignments(agent_id: str):
        if not runtime.assignment_service:
            return {"assignments": []}
        assignments = await runtime.assignment_service.get_agent_assignments(agent_id)
        return {"assignments": [vars(a) for a in assignments]}

    # --- Scheduled Tasks (Phase 25a) ---

    @app.get("/api/scheduled-tasks")
    async def list_scheduled_tasks(status: str | None = None) -> dict[str, Any]:
        """List persistent scheduled tasks."""
        if not runtime.persistent_task_store:
            return {"tasks": [], "error": "Persistent task store not enabled"}
        tasks = await runtime.persistent_task_store.list_tasks(status=status)
        return {"tasks": [runtime.persistent_task_store._task_to_dict(t) for t in tasks]}

    @app.post("/api/scheduled-tasks")
    async def create_scheduled_task(req: ScheduledTaskRequest) -> dict[str, Any]:
        """Create a new persistent scheduled task."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        try:
            task = await runtime.persistent_task_store.create_task(
                intent_text=req.intent_text,
                schedule_type=req.schedule_type,
                name=req.name,
                execute_at=req.execute_at,
                interval_seconds=req.interval_seconds,
                cron_expr=req.cron_expr,
                channel_id=req.channel_id,
                max_runs=req.max_runs,
                created_by=req.created_by,
                webhook_name=req.webhook_name,
                agent_hint=req.agent_hint,    # AD-418
            )
            return runtime.persistent_task_store._task_to_dict(task)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/scheduled-tasks/{task_id}")
    async def get_scheduled_task(task_id: str) -> dict[str, Any]:
        """Get a single scheduled task by ID."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        task = await runtime.persistent_task_store.get_task(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        return runtime.persistent_task_store._task_to_dict(task)

    @app.delete("/api/scheduled-tasks/{task_id}")
    async def cancel_scheduled_task(task_id: str) -> dict[str, Any]:
        """Cancel a scheduled task."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        cancelled = await runtime.persistent_task_store.cancel_task(task_id)
        if not cancelled:
            return JSONResponse(status_code=404, content={"error": "Task not found or already cancelled"})
        return {"cancelled": True, "task_id": task_id}

    class UpdateAgentHintRequest(BaseModel):
        agent_hint: str | None = None

    @app.patch("/api/scheduled-tasks/{task_id}/hint")
    async def update_task_agent_hint(
        task_id: str, req: UpdateAgentHintRequest,
    ) -> dict[str, Any]:
        """AD-418: Update a scheduled task's agent_hint for routing bias."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        task = await runtime.persistent_task_store.get_task(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        # Direct DB update
        async with runtime.persistent_task_store._db.execute(
            "UPDATE scheduled_tasks SET agent_hint = ? WHERE id = ?",
            (req.agent_hint, task_id),
        ) as _:
            pass
        await runtime.persistent_task_store._db.commit()
        updated = await runtime.persistent_task_store.get_task(task_id)
        return runtime.persistent_task_store._task_to_dict(updated)

    @app.post("/api/scheduled-tasks/webhook/{webhook_name}")
    async def trigger_webhook(webhook_name: str) -> dict[str, Any]:
        """Trigger a named webhook task."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        task = await runtime.persistent_task_store.trigger_webhook(webhook_name)
        if not task:
            return JSONResponse(status_code=404, content={"error": f"Webhook '{webhook_name}' not found"})
        return {"triggered": True, "task_id": task.id, "webhook_name": webhook_name}

    @app.post("/api/scheduled-tasks/dag/{dag_id}/resume")
    async def resume_dag_checkpoint(dag_id: str) -> dict[str, Any]:
        """Resume a stale DAG checkpoint (Captain-approved)."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        result = await runtime.persistent_task_store.resume_dag(dag_id)
        if "error" in result:
            return JSONResponse(status_code=400, content=result)
        return result

    async def _run_build(
        req: BuildRequest,
        build_id: str,
        rt: Any,
    ) -> None:
        """Background build pipeline with WebSocket progress events."""
        try:
            rt._emit_event("build_started", {
                "build_id": build_id,
                "title": req.title,
                "message": f"Starting build: {req.title}...",
            })

            rt._emit_event("build_progress", {
                "build_id": build_id,
                "step": "preparing",
                "step_label": "\u25c8 Preparing build context...",
                "current": 1,
                "total": 3,
                "message": "\u25c8 Reading reference files...",
            })

            rt._emit_event("build_progress", {
                "build_id": build_id,
                "step": "generating",
                "step_label": "\u2b21 Generating code...",
                "current": 2,
                "total": 3,
                "message": "\u2b21 Generating code via deep LLM...",
            })

            from probos.types import IntentMessage
            intent = IntentMessage(
                intent="build_code",
                params={
                    "title": req.title,
                    "description": req.description,
                    "target_files": req.target_files,
                    "reference_files": req.reference_files,
                    "test_files": req.test_files,
                    "ad_number": req.ad_number,
                    "constraints": req.constraints,
                    "force_native": req.force_native,
                    "force_visiting": req.force_visiting,
                    "model": req.model,
                },
                ttl_seconds=600.0,  # Builder works asynchronously — no rush
            )

            results = await rt.intent_bus.broadcast(intent)

            build_result = None
            for r in results:
                if r and r.success and r.result:
                    build_result = r
                    break

            if not build_result or not build_result.result:
                error_msg = "BuilderAgent returned no results"
                if results:
                    errors = [r.error for r in results if r and r.error]
                    if errors:
                        error_msg = "; ".join(errors)
                rt._emit_event("build_failure", {
                    "build_id": build_id,
                    "message": f"Build failed: {error_msg}",
                    "error": error_msg,
                })
                return

            rt._emit_event("build_progress", {
                "build_id": build_id,
                "step": "review",
                "step_label": "\u25ce Ready for review",
                "current": 3,
                "total": 3,
                "message": "\u25ce Code generated \u2014 awaiting Captain approval",
            })

            result_data = build_result.result
            if isinstance(result_data, str):
                import json as _json
                try:
                    result_data = _json.loads(result_data)
                except Exception:
                    result_data = {"llm_output": result_data, "file_changes": [], "change_count": 0}

            file_changes = result_data.get("file_changes", [])
            change_count = result_data.get("change_count", len(file_changes))
            llm_output = result_data.get("llm_output", "")
            builder_source = result_data.get("builder_source", "native")

            rt._emit_event("build_generated", {
                "build_id": build_id,
                "title": req.title,
                "description": req.description,
                "ad_number": req.ad_number,
                "file_changes": file_changes,
                "change_count": change_count,
                "llm_output": llm_output,
                "builder_source": builder_source,
                "message": f"Generated {change_count} file(s) for '{req.title}' \u2014 review and approve to apply.",
            })

        except Exception as e:
            logger.warning("Build pipeline failed: %s", e, exc_info=True)
            rt._emit_event("build_failure", {
                "build_id": build_id,
                "message": f"Build failed: {e}",
                "error": str(e),
            })

    async def _execute_build(
        build_id: str,
        file_changes: list[dict],
        spec: Any,
        work_dir: str,
        rt: Any,
    ) -> None:
        """Background execution of approved build."""
        from probos.cognitive.builder import execute_approved_build

        try:
            rt._emit_event("build_progress", {
                "build_id": build_id,
                "step": "writing",
                "step_label": "\u25c8 Writing files...",
                "current": 1,
                "total": 3,
                "message": "\u25c8 Writing files to disk...",
            })

            result = await execute_approved_build(
                file_changes=file_changes,
                spec=spec,
                work_dir=work_dir,
                run_tests=True,
                llm_client=getattr(rt, "llm_client", None),
                escalation_hook=None,  # TODO(Phase-33): wire to ChainOfCommand
            )

            if result.success:
                rt._emit_event("build_success", {
                    "build_id": build_id,
                    "branch": result.branch_name,
                    "commit": result.commit_hash,
                    "files_written": result.files_written + result.files_modified,
                    "tests_passed": result.tests_passed,
                    "test_result": result.test_result[:500] if result.test_result else "",
                    "review": result.review_result,
                    "review_issues": result.review_issues,
                    "message": (
                        f"\u2b22 Build complete! Branch: {result.branch_name}, "
                        f"Commit: {result.commit_hash}, "
                        f"Files: {len(result.files_written) + len(result.files_modified)}, "
                        f"Tests: {'passed' if result.tests_passed else 'FAILED'}"
                    ),
                })
            else:
                # Build failed — produce structured diagnostic (AD-345)
                from probos.cognitive.builder import classify_build_failure
                report = classify_build_failure(result, spec)
                report.build_id = build_id

                # Cache build context for resolution endpoint
                _clean_expired_failures()
                _pending_failures[build_id] = {
                    "file_changes": file_changes,
                    "spec": spec,
                    "work_dir": work_dir,
                    "report": report,
                    "timestamp": time.time(),
                }

                rt._emit_event("build_failure", {
                    "build_id": build_id,
                    "message": f"Build failed: {report.failure_summary}",
                    "report": report.to_dict(),
                })
        except Exception as e:
            logger.warning("Build execution failed: %s", e, exc_info=True)
            rt._emit_event("build_failure", {
                "build_id": build_id,
                "message": f"Build execution failed: {e}",
                "error": str(e),
            })

    # ------------------------------------------------------------------
    # Architect Agent API (AD-308)
    # ------------------------------------------------------------------

    @app.post("/api/design/submit")
    async def submit_design(req: DesignRequest) -> dict[str, Any]:
        """Start async architectural design. Progress via WebSocket events."""
        import uuid
        design_id = uuid.uuid4().hex[:12]
        _track_task(_run_design(req, design_id, runtime), name=f"design-{design_id}")
        return {
            "status": "started",
            "design_id": design_id,
            "message": f"Design request for '{req.feature}' started...",
        }

    @app.post("/api/design/approve")
    async def approve_design(req: DesignApproveRequest) -> dict[str, Any]:
        """Approve architect proposal — forwards embedded BuildSpec to builder."""
        if req.design_id not in _pending_designs:
            return {"status": "error", "message": f"Design {req.design_id} not found or already processed"}

        proposal_data = _pending_designs.pop(req.design_id)
        build_spec = proposal_data["build_spec"]

        import uuid
        build_id = uuid.uuid4().hex[:12]
        build_req = BuildRequest(
            title=build_spec.get("title", ""),
            description=build_spec.get("description", ""),
            target_files=build_spec.get("target_files", []),
            reference_files=build_spec.get("reference_files", []),
            test_files=build_spec.get("test_files", []),
            ad_number=build_spec.get("ad_number", 0),
            constraints=build_spec.get("constraints", []),
        )
        _track_task(_run_build(build_req, build_id, runtime), name=f"build-{build_id}")

        return {
            "status": "forwarded",
            "design_id": req.design_id,
            "build_id": build_id,
            "message": f"Proposal approved \u2014 forwarded to Builder (build_id: {build_id})",
        }

    async def _run_design(
        req: DesignRequest,
        design_id: str,
        rt: Any,
    ) -> None:
        """Background design pipeline with WebSocket progress events."""
        try:
            rt._emit_event("design_started", {
                "design_id": design_id,
                "feature": req.feature,
                "message": f"Architect analyzing: {req.feature}...",
            })

            rt._emit_event("design_progress", {
                "design_id": design_id,
                "step": "surveying",
                "step_label": "\u2609 Surveying codebase...",
                "current": 1,
                "total": 3,
                "message": "\u2609 Surveying codebase and roadmap...",
            })

            rt._emit_event("design_progress", {
                "design_id": design_id,
                "step": "designing",
                "step_label": "\u2b21 Designing specification...",
                "current": 2,
                "total": 3,
                "message": "\u2b21 Generating architectural proposal via deep LLM...",
            })

            from probos.types import IntentMessage
            intent = IntentMessage(
                intent="design_feature",
                params={
                    "feature": req.feature,
                    "phase": req.phase,
                },
                ttl_seconds=600.0,  # Architect works asynchronously — no rush
            )

            results = await rt.intent_bus.broadcast(intent)

            design_result = None
            for r in results:
                if r and r.success and r.result:
                    design_result = r
                    break

            if not design_result or not design_result.result:
                error_msg = "ArchitectAgent returned no results"
                if results:
                    errors = [r.error for r in results if r and r.error]
                    if errors:
                        error_msg = "; ".join(errors)
                rt._emit_event("design_failure", {
                    "design_id": design_id,
                    "message": f"Design failed: {error_msg}",
                    "error": error_msg,
                })
                return

            rt._emit_event("design_progress", {
                "design_id": design_id,
                "step": "review",
                "step_label": "\u25ce Ready for review",
                "current": 3,
                "total": 3,
                "message": "\u25ce Proposal ready \u2014 awaiting Captain review",
            })

            result_data = design_result.result
            if isinstance(result_data, str):
                import json as _json
                try:
                    result_data = _json.loads(result_data)
                except Exception:
                    result_data = {"proposal": {}, "llm_output": result_data}

            proposal = result_data.get("proposal", {})
            llm_output = result_data.get("llm_output", "")

            # Store proposal for later approval
            _pending_designs[design_id] = {
                "proposal": proposal,
                "build_spec": proposal.get("build_spec", {}),
            }

            rt._emit_event("design_generated", {
                "design_id": design_id,
                "title": proposal.get("title", req.feature),
                "summary": proposal.get("summary", ""),
                "rationale": proposal.get("rationale", ""),
                "roadmap_ref": proposal.get("roadmap_ref", ""),
                "priority": proposal.get("priority", "medium"),
                "dependencies": proposal.get("dependencies", []),
                "risks": proposal.get("risks", []),
                "build_spec": proposal.get("build_spec", {}),
                "llm_output": llm_output,
                "message": f"Architect proposes: {proposal.get('title', req.feature)} \u2014 review and approve to forward to Builder.",
            })

        except Exception as e:
            logger.warning("Design pipeline failed: %s", e, exc_info=True)
            rt._emit_event("design_failure", {
                "design_id": design_id,
                "message": f"Design failed: {e}",
                "error": str(e),
            })

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
                # Client disconnected or errored — prune from list
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

        for ws in list(_ws_clients):
            asyncio.create_task(_safe_send(ws, safe_event))

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
