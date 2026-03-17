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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Commands that should NOT be available via the API
_BLOCKED_COMMANDS = {'/quit', '/debug'}


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
            from probos.channels.response_formatter import extract_response_text
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

        asyncio.create_task(_run_selfmod(req, runtime))

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
                rt.self_mod_pipeline._import_approval_fn = _auto_approve_imports

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
                if rt._knowledge_store:
                    try:
                        await rt._knowledge_store.store_agent(record, record.source_code)
                    except Exception:
                        pass
                if rt._semantic_layer:
                    try:
                        await rt._semantic_layer.index_agent(
                            agent_type=record.agent_type,
                            intent_name=record.intent_name,
                            description=record.intent_name,
                            strategy=record.strategy,
                            source_snippet=record.source_code[:200] if record.source_code else "",
                        )
                    except Exception:
                        pass

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

                rt._emit_event("self_mod_success", {
                    "intent": req.intent_name,
                    "agent_type": record.agent_type,
                    "message": deploy_msg,
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
        for ws in list(_ws_clients):
            try:
                asyncio.create_task(ws.send_json(safe_event))
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
