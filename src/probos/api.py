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
