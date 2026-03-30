"""ProbOS API — Chat & Self-Mod routes (AD-247, AD-308)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request

from probos.api_models import (
    BuildRequest, ChatRequest, DesignRequest,
    EnrichRequest, SelfModRequest,
)
from probos.routers.deps import (
    get_pending_designs, get_runtime, get_task_tracker, get_ws_broadcast,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(
    req: ChatRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
    broadcast: Callable = Depends(get_ws_broadcast),
    pending_designs: dict = Depends(get_pending_designs),
) -> dict[str, Any]:
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
            from probos.routers.build import _run_build
            build_id = uuid.uuid4().hex[:12]
            track_task(_run_build(
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
            from probos.routers.design import _run_design
            design_id = _uuid_design.uuid4().hex[:12]
            track_task(_run_design(
                DesignRequest(feature=feature, phase=phase),
                design_id,
                runtime,
                pending_designs,
            ), name=f"design-{design_id}")
            return {
                "response": f"Design request submitted (id: {design_id}). The Architect is analyzing...",
                "design_id": design_id,
                "dag": None,
                "results": None,
            }
        from probos.api import _handle_slash_command
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
        broadcast(evt)

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


@router.post("/selfmod/approve")
async def approve_selfmod(
    req: SelfModRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """Start async self-mod pipeline. Progress via WebSocket events."""
    if not getattr(runtime, 'self_mod_pipeline', None):
        return {"response": "Self-modification is not enabled.", "status": "error"}

    track_task(_run_selfmod(req, runtime), name="selfmod")

    return {
        "response": "Starting agent design...",
        "status": "started",
    }


@router.post("/selfmod/enrich")
async def enrich_selfmod(
    req: EnrichRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
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
