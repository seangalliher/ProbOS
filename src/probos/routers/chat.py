"""ProbOS API — Chat & Self-Mod routes (AD-247, AD-308)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from probos.api_models import (
    BuildRequest, ChatRequest, ChatToolGrantRequest, DesignRequest,
    EnrichRequest, SelfModRequest,
)
from probos.events import EventType
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
    # BF #467: only treat as DM directive when @callsign is the leading token.
    # "@Tucker hello" -> DM. "Hello @Tucker, can you help?" -> broadcast.
    from probos.crew_profile import (
        extract_all_leading_callsign_mentions,
        extract_callsign_mention,
        is_directed_mention,
    )

    # BF (2026-05-11): Attachment augmentation for callsign-DM paths.
    # The mention-fan-out and legacy single-mention branches below early-return
    # without running the attachment pipeline at line ~257, silently dropping
    # any image / PDF / text attachment when the message starts with @callsign.
    # When a mention is present AND there are attachments, augment `text`
    # (and `req.message`) with extracted attachment text + image markers so
    # the receiving agent at least sees the attachment in its prompt.
    # Tier-2 log-and-degrade: failures fall back to original text.
    if req.attachment_ids and is_directed_mention(text):
        _cfg_attach = getattr(runtime.config, "attachments", None)
        if _cfg_attach is not None and getattr(_cfg_attach, "enabled", False):
            from probos.cognitive.vision_dispatch import (
                augment_prompt_with_attachment_text,
            )
            _store = _get_attachment_store(runtime)

            async def _mime_lookup_dm(content_hash: str) -> str | None:
                return await _store.mime_for(content_hash)

            augmented = await augment_prompt_with_attachment_text(
                prompt=text,
                attachment_ids=list(req.attachment_ids),
                store=_store,
                mime_lookup=_mime_lookup_dm,
                text_extraction_max_bytes=_cfg_attach.text_extraction_max_bytes,
                pdf_extraction_enabled=_cfg_attach.pdf_extraction_enabled,
            )
            if augmented != text:
                text = augmented
                req = req.model_copy(update={"message": augmented})

    # AD-719: multi-mention fan-out branch — also handles SINGLE mentions
    # (>= 1) so attribution + episodic-write parity is consistent. The legacy
    # single-mention DM path below is kept only as fall-through for unrelated
    # callsign edge cases (parse misses).
    if is_directed_mention(text):
        all_callsigns, remaining_message = extract_all_leading_callsign_mentions(text)
        # BF-287 (2026-05-13): AD-719 spec was single-mention → legacy DM
        # path (response field), multi-mention → fan-out (per_agent_replies).
        # The original implementation used ``>= 1`` which caught EVERY mention
        # in the fan-out branch, breaking the four AD-719 single-mention
        # contract tests + producing "(callsign not recognized)" stubs for
        # unresolved single mentions instead of falling through to NL. ``>= 2``
        # restores the documented behavior.
        if len(all_callsigns) >= 2:
            t_start_fanout = time.monotonic()
            from probos.api_models import PerAgentReply
            from probos.types import IntentMessage as _IntentMessage

            resolved_list: list[tuple[str, dict[str, Any] | None]] = []
            for cs in all_callsigns:
                resolved_list.append((cs, runtime.callsign_registry.resolve(cs)))

            async def _send_one(callsign: str, resolved: dict[str, Any] | None) -> PerAgentReply:
                if resolved is None:
                    return PerAgentReply(
                        agent_id="",
                        callsign=callsign,
                        text="(callsign not recognized)",
                    )
                if resolved.get("agent_id") is None:
                    return PerAgentReply(
                        agent_id="",
                        callsign=resolved.get("callsign", callsign),
                        text="(not currently on duty)",
                    )
                if not remaining_message:
                    return PerAgentReply(
                        agent_id=resolved["agent_id"],
                        callsign=resolved["callsign"],
                        text="(no message — append text after the mentions)",
                    )
                intent = _IntentMessage(
                    intent="direct_message",
                    params={
                        "text": remaining_message,
                        "from": "hxi_profile",  # match per-agent chat path so agent direct_message handler treats it as a real DM
                        "session": True,
                        "session_history": [],
                    },
                    target_agent_id=resolved["agent_id"],
                    ttl_seconds=60.0,  # AD-636
                )
                try:
                    result = await runtime.intent_bus.send(intent)
                except Exception as e:
                    logger.warning(
                        "AD-719 fan-out send failed for %s: %s: %s; "
                        "returning stub reply, other recipients unaffected",
                        resolved.get("callsign", callsign), type(e).__name__, e,
                    )
                    return PerAgentReply(
                        agent_id=resolved["agent_id"],
                        callsign=resolved["callsign"],
                        text="(delivery failed)",
                    )
                reply_text = (result.result if result and result.result else "(no response)")
                return PerAgentReply(
                    agent_id=resolved["agent_id"],
                    callsign=resolved["callsign"],
                    text=str(reply_text),
                )

            per_agent_replies_list = await asyncio.gather(
                *[_send_one(cs, r) for cs, r in resolved_list],
            )
            per_agent_replies = list(per_agent_replies_list)

            # Episodic write per resolved fan-out reply (one episode per
            # (captain_turn, replying_agent) pair). Stubs (unresolved /
            # off-duty / delivery-failed without an agent_id) are skipped.
            episodic_memory = getattr(runtime, "episodic_memory", None)
            if episodic_memory is not None:
                t_end_fanout = time.monotonic()
                dream_adapter = getattr(runtime, "dream_adapter", None)
                for reply in per_agent_replies:
                    if not reply.agent_id:
                        continue
                    try:
                        episode_input = f"@{reply.callsign} {remaining_message}"
                        if dream_adapter is not None:
                            episode = dream_adapter.build_episode(
                                episode_input,
                                {"response": reply.text, "agent_ids": [reply.agent_id]},
                                t_start_fanout,
                                t_end_fanout,
                            )
                        else:
                            from probos.types import AnchorFrame, Episode
                            episode = Episode(
                                timestamp=time.time(),
                                user_input=episode_input,
                                dag_summary={},
                                outcomes=[],
                                agent_ids=[reply.agent_id],
                                duration_ms=(t_end_fanout - t_start_fanout) * 1000,
                                source="multi_agent_chat",  # AD-719 distinct tag
                                anchors=AnchorFrame(
                                    channel="chat",
                                    trigger_type="at_mention_fanout",
                                ),
                            )
                        await episodic_memory.store(episode)
                    except Exception as e:
                        logger.warning(
                            "AD-719 fan-out episode store failed for %s: %s: %s; "
                            "continuing — episodic gap accepted, replies still returned",
                            reply.callsign, type(e).__name__, e,
                        )

            return {
                "response": "",
                "dag": None,
                "results": None,
                "mentions": all_callsigns,
                "per_agent_replies": [r.model_dump() for r in per_agent_replies],
            }

    mention = extract_callsign_mention(text)
    if mention and is_directed_mention(text):
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
                ttl_seconds=60.0,  # AD-636: Extended TTL for Captain DMs
            )
            result = await runtime.intent_bus.send(intent)
            response = f"{resolved['callsign']}: {result.result}" if result and result.result else f"{resolved['callsign']}: (no response)"
            return {"response": response, "dag": None, "results": None}
        # Callsign not found — fall through to NL processing

    # AD-720d (Wave 139): vision pipe-through + non-image inline extraction.
    # Fires only when the user attached files. Zero-attachment turns are
    # bit-for-bit unchanged (the existing decomposer path runs as before).
    if req.attachment_ids:
        cfg_attach = getattr(runtime.config, "attachments", None)
        if cfg_attach is not None and getattr(cfg_attach, "enabled", False):
            from probos.cognitive.text_extractor import extract_text  # noqa: F401
            from probos.cognitive.vision_dispatch import build_multimodal_messages
            from probos.types import LLMRequest

            store = _get_attachment_store(runtime)

            async def _mime_lookup(content_hash: str) -> str | None:
                return await store.mime_for(content_hash)

            messages, image_ids, per_attachment = await build_multimodal_messages(
                prompt=text,
                attachment_ids=list(req.attachment_ids),
                store=store,
                mime_lookup=_mime_lookup,
                text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
            )

            if image_ids:
                # AD-720d-1: soft warning when image count exceeds the operator
                # threshold. Log-only; never blocks or truncates. Cap the
                # logged attachment_ids list at the first 10 entries for log
                # hygiene when the operator sends large batches.
                warn_threshold = getattr(cfg_attach, "multi_image_warn_threshold", 0)
                if warn_threshold and len(image_ids) > warn_threshold:
                    capped = list(req.attachment_ids)[:10]
                    logger.warning(
                        "AD-720d-1: /api/chat vision turn includes %d images "
                        "(threshold=%d); this may exceed the LLM's effective "
                        "context budget — proceeding without truncation. "
                        "attachment_ids[:10]=%s",
                        len(image_ids), warn_threshold, capped,
                    )
                tier = cfg_attach.vision_tier
                # AD-730-5: /api/chat vision branch is untargeted (Captain
                # composing with the LLM directly — no specific agent in
                # scope), so agent_type is empty. The helper returns the
                # default tier unchanged. The override map exists for
                # per-agent DMs (routers/agents.py) and for future
                # directed-mention cases.
                from probos.cognitive.vision_dispatch import (
                    resolve_vision_tier_for_agent,
                )
                tier = resolve_vision_tier_for_agent(cfg_attach, "", tier)
                health = runtime.llm_client.get_health_status()
                tier_status = (health.get("tiers", {}).get(tier) or {}).get("status")
                from probos.cognitive.vision_dispatch import (
                    VISION_UNCONFIGURED_MESSAGE,
                    VISION_UNHEALTHY_MESSAGE,
                    is_vision_tier_configured,
                )
                # AD-732: honest-degrade fires if vision is either
                # unconfigured (no endpoint set) or unhealthy (probe-failed).
                # Two distinct messages because the remediations differ.
                configured = is_vision_tier_configured(
                    runtime.config.cognitive, tier
                )
                # BF-271 (2026-05-12): 'recovering' is operational. Tier
                # responded successfully recently but hasn't met the dwell
                # threshold to clear failure counter — refusing to use it
                # would produce honest-degrade for a working endpoint.
                if not configured or tier_status not in ("operational", "recovering"):
                    if not configured:
                        logger.info(
                            "AD-732: /api/chat vision DM requested but vision "
                            "tier unconfigured; returning honest-degrade "
                            "message. attachment_ids=%s",
                            list(req.attachment_ids),
                        )
                        return {
                            "response": VISION_UNCONFIGURED_MESSAGE,
                            "dag": None,
                            "results": None,
                        }
                    logger.warning(
                        "AD-732: /api/chat vision tier=%s configured but "
                        "unhealthy (status=%s); returning honest-degrade "
                        "message. attachment_ids=%s",
                        tier, tier_status, list(req.attachment_ids),
                    )
                    return {
                        "response": VISION_UNHEALTHY_MESSAGE,
                        "dag": None,
                        "results": None,
                    }
                t_start_vision = time.monotonic()
                llm_response = await runtime.llm_client.complete(
                    LLMRequest(
                        prompt="",
                        messages=messages,
                        tier=tier,
                        max_tokens=2048,
                    ),
                )
                t_end_vision = time.monotonic()

                # AD-720d-3: episodic write for vision-routed /api/chat turns.
                # The standard NL path stores an episode after decomposition,
                # but this branch short-circuits via `return` below — so the
                # turn would be invisible to recall/dreaming without this block.
                # Tier-2 log-and-degrade: write failures must not block the reply.
                episodic_memory = getattr(runtime, "episodic_memory", None)
                if episodic_memory is not None:
                    try:
                        from probos.types import AnchorFrame, Episode
                        episode = Episode(
                            timestamp=time.time(),
                            user_input=text,
                            dag_summary={},
                            outcomes=[{
                                "intent": "captain_chat_vision",
                                "success": True,
                                "response": (llm_response.content or "")[:500],
                                "has_image_attachment": True,
                                "image_count": len(image_ids),
                                # AD-720d-1: partial-resolve metric +
                                # per-attachment latency for dreaming/recall.
                                "failed_image_count": sum(1 for r in per_attachment if not r["ok"]),
                                "per_attachment_timing": per_attachment,
                                "attachment_ids": list(req.attachment_ids),
                                "llm_tier": tier,
                                "llm_model": getattr(llm_response, "model", ""),
                            }],
                            agent_ids=["captain"],
                            duration_ms=(t_end_vision - t_start_vision) * 1000,
                            source="captain_chat",
                            anchors=AnchorFrame(
                                channel="captain_chat",
                                trigger_type="vision_attachment",
                            ),
                        )
                        await episodic_memory.store(episode)
                    except Exception:
                        logger.debug(
                            "AD-720d-3: vision episode store failed; "
                            "continuing — reply unaffected",
                            exc_info=True,
                        )

                return {
                    "response": llm_response.content or "(no response)",
                    "dag": None,
                    "results": None,
                }

            # Non-image only: synthesize an augmented prompt and fall through
            # to the standard NL decomposer path. The augmented prompt gets the
            # same treatment as a normal text turn (decomposition, episodic, etc.).
            text_blocks = [
                item.get("text", "")
                for item in messages[0]["content"]
                if item.get("type") == "text" and item.get("text") != text
            ]
            if text_blocks:
                augmented = text + "\n\n" + "\n\n".join(text_blocks)
                req = req.model_copy(update={"message": augmented})
                text = req.message

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
        # BF-108: If MockLLMClient is active, tell the user directly
        if getattr(runtime, "llm_is_mock", False):
            response_text = (
                "LLM is offline — running on MockLLMClient "
                "(pattern-matched responses only). "
                "Start the Copilot Proxy or Ollama and restart ProbOS."
            )
        else:
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
                    logger.debug("Chat context failed", exc_info=True)

            if diag_parts:
                response_text = " | ".join(diag_parts)
            else:
                response_text = (
                    "(Empty response — check probos serve terminal)"
                )

    # Check for self-mod proposal (capability gap detected, API mode)
    # BF-108: Skip self-mod when MockLLMClient is active — no point offering
    # to build agents when LLM can't run them.
    self_mod = dag_result.get("self_mod")
    self_mod_proposal: dict[str, Any] | None = None
    is_mock = getattr(runtime, "llm_is_mock", False)
    if self_mod and self_mod.get("status") == "proposed" and not is_mock:
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
# Chat attachments (AD-720) — image paste v1
# ------------------------------------------------------------------


_ATTACHMENT_STORE_CACHE: dict[int, Any] = {}


def _get_attachment_store(runtime: Any) -> Any:
    """Lazy per-runtime FilesystemAttachmentStore."""
    key = id(runtime)
    cached = _ATTACHMENT_STORE_CACHE.get(key)
    if cached is not None:
        return cached
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.attachments.store import _resolve_attachments_dir
    cfg = runtime.config.attachments
    root = _resolve_attachments_dir(cfg.attachments_dir)
    store = FilesystemAttachmentStore(root)
    _ATTACHMENT_STORE_CACHE[key] = store
    return store


async def _validate_and_store_attachment(
    runtime: Any,
    blob: bytes,
    declared_mime: str,
    declared_filename: str | None,
    declared_hash_or_None: str | None,
) -> tuple[bool, dict[str, Any]]:
    """AD-720a: shared defense-in-depth chain for both POST endpoints.

    Returns ``(True, response_payload)`` on success, or
    ``(False, {"status_code": int, "body": {...}})`` on rejection.

    Both the JSON+base64 path (``upload_chat_attachment``) and the multipart
    path (``upload_chat_attachment_multipart``) call this helper. The chain
    is the single source of truth for the attachment defense-in-depth gate.
    """
    import hashlib

    from probos.attachments.mime import validate_attachment_bytes

    cfg = runtime.config.attachments

    # 1. Feature gate.
    if not cfg.enabled:
        return (False, {"status_code": 503, "body": {"error": "attachments_disabled"}})

    # 2. MIME allowlist.
    if declared_mime not in cfg.allowed_mime_types:
        return (
            False,
            {
                "status_code": 415,
                "body": {"error": "mime_not_allowed", "mime": declared_mime},
            },
        )

    # 3. Size cap.
    if len(blob) > cfg.max_attachment_bytes:
        return (
            False,
            {
                "status_code": 413,
                "body": {
                    "error": "too_large",
                    "size": len(blob),
                    "max": cfg.max_attachment_bytes,
                },
            },
        )

    # 4. sha256 — compute once, optionally cross-check the client-supplied hash.
    actual_hash = hashlib.sha256(blob).hexdigest()
    if declared_hash_or_None is not None:
        if actual_hash != declared_hash_or_None.lower():
            return (False, {"status_code": 400, "body": {"error": "hash_mismatch"}})

    # 5. Magic-byte + parse-attempt + extension check.
    ok, sniffed_or_reason = validate_attachment_bytes(blob, declared_mime, declared_filename)
    if not ok:
        logger.warning(
            "AD-720a attachment rejected at validator: declared=%s filename=%s reason=%s size=%d",
            declared_mime, declared_filename, sniffed_or_reason, len(blob),
        )
        return (
            False,
            {
                "status_code": 415,
                "body": {
                    "error": "magic_mismatch",
                    "declared": declared_mime,
                    "sniffed": sniffed_or_reason,
                },
            },
        )

    # 6. Idempotent write — propagate path-traversal / malformed-hash as 400.
    store = _get_attachment_store(runtime)
    try:
        await store.write(actual_hash, blob, declared_mime)
    except ValueError as e:
        logger.error(
            "AD-720a attachment write rejected (security tier): %s: %s",
            type(e).__name__, e,
        )
        return (False, {"status_code": 400, "body": {"error": "invalid_attachment"}})

    return (
        True,
        {
            "attachment_id": actual_hash,
            "url": f"/api/chat/attachments/{actual_hash}",
            "mime": declared_mime,
            "size_bytes": len(blob),
            "sha256": actual_hash,
        },
    )


@router.post("/chat/attachments")
async def upload_chat_attachment(
    req: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-720: image-paste upload endpoint. JSON body, base64-encoded blob.

    Defense-in-depth chain delegated to ``_validate_and_store_attachment``
    (AD-720a, Wave 139). Behaviour is bit-for-bit equivalent to the pre-AD-720a
    inline implementation; the existing AD-720 paste tests are the regression
    guard.
    """
    import base64
    import binascii

    from probos.api_models import AttachmentUploadRequest

    payload = await req.json()
    try:
        body = AttachmentUploadRequest.model_validate(payload)
    except Exception as e:
        logger.warning(
            "AD-720 attachment upload rejected (malformed body): %s: %s",
            type(e).__name__, e,
        )
        return JSONResponse(status_code=400, content={"error": "invalid_body"})

    try:
        decoded = base64.b64decode(body.blob_b64, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=400, content={"error": "invalid_base64"})

    ok, result = await _validate_and_store_attachment(
        runtime,
        decoded,
        body.mime,
        declared_filename=None,
        declared_hash_or_None=body.content_hash,
    )
    if not ok:
        return JSONResponse(status_code=result["status_code"], content=result["body"])
    return result


@router.post("/chat/attachments/multipart")
async def upload_chat_attachment_multipart(
    file: UploadFile = File(...),
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-720a (Wave 139): multipart upload endpoint.

    Reads bytes once via ``await file.read()``. Server computes sha256 — there
    is no client-supplied content_hash on this endpoint. Filename and MIME come
    from the FastAPI ``UploadFile`` (set by the multipart parser). Calls the
    same shared ``_validate_and_store_attachment`` helper as the JSON path.
    """
    declared_mime = file.content_type or "application/octet-stream"
    declared_filename = file.filename
    blob = await file.read()

    ok, result = await _validate_and_store_attachment(
        runtime,
        blob,
        declared_mime,
        declared_filename=declared_filename,
        declared_hash_or_None=None,
    )
    if not ok:
        return JSONResponse(status_code=result["status_code"], content=result["body"])
    return result


@router.get("/chat/attachments/{content_hash}")
async def fetch_chat_attachment(
    content_hash: str,
    runtime: Any = Depends(get_runtime),
) -> FileResponse:
    """AD-720: serve a previously-stored attachment by sha256.

    The store's content-addressed filenames make this safe — the hash
    pattern is constrained to [0-9a-f]{64}, no path traversal possible.
    Path resolution still goes through the same _resolve_attachments_dir
    guard that the POST uses.
    """
    if not (len(content_hash) == 64 and all(c in "0123456789abcdef" for c in content_hash)):
        raise HTTPException(status_code=400, detail="invalid_content_hash")
    cfg = getattr(runtime.config, "attachments", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        raise HTTPException(status_code=404, detail="attachments_disabled")
    store = _get_attachment_store(runtime)
    if not await store.exists(content_hash):
        raise HTTPException(status_code=404, detail="attachment_not_found")
    path = await store.get_path(content_hash)
    # AD-720a: MIME inferred via the ext_to_mime helper (single source of truth
    # backed by ``_MIME_TO_EXT``). The upload validator ensured the extension
    # matches the magic bytes.
    from probos.attachments.filesystem_store import ext_to_mime
    mime = ext_to_mime(path.suffix)
    return FileResponse(path, media_type=mime)


# ------------------------------------------------------------------
# Self-mod approval endpoint (async pipeline)
# ------------------------------------------------------------------


@router.post("/chat/tool-grant")
async def chat_tool_grant(
    req: ChatToolGrantRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-720b: Captain issues a scoped tool capability grant from inside a DM.

    Persistence flows through the existing ``ToolPermissionStore.issue_grant``
    (AD-423a/b/c) so a grant issued here is indistinguishable on disk from
    one issued via ``/tool-access grant`` in the shell. ``issued_by`` is
    always ``"captain"`` (matches the slash-command pattern; the HXI runs
    in the Captain's process context).
    """
    from probos.tools.protocol import ToolPermission

    if runtime.registry.get(req.agent_id) is None:
        raise HTTPException(status_code=404, detail=f"Agent {req.agent_id} not found")

    try:
        perm = ToolPermission(req.permission)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "invalid_permission",
                "valid": [p.value for p in ToolPermission],
            },
        )

    tool_registry = getattr(runtime, "tool_registry", None)
    if tool_registry is not None and tool_registry.get(req.tool_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "tool_not_found", "tool_id": req.tool_id},
        )

    store = getattr(runtime, "tool_permission_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="tool_permission_store_unavailable",
        )

    expires_at: float | None = None
    if req.duration_hours is not None and req.duration_hours > 0:
        import time as _time
        expires_at = _time.time() + req.duration_hours * 3600.0

    grant = await store.issue_grant(
        agent_id=req.agent_id,
        tool_id=req.tool_id,
        permission=perm,
        reason=req.reason,
        issued_by="captain",
        expires_at=expires_at,
    )

    try:
        runtime.emit_event(
            "tool_grant_issued",
            {
                "grant_id": grant.id,
                "agent_id": grant.agent_id,
                "tool_id": grant.tool_id,
                "permission": grant.permission.value,
                "expires_at": grant.expires_at,
                "issued_by": grant.issued_by,
                "source": "chat",
            },
        )
    except Exception:
        logger.warning(
            "AD-720b: emit_event('tool_grant_issued') failed for grant %s; "
            "grant persisted but audit lost",
            grant.id, exc_info=True,
        )

    return {
        "grant_id": grant.id,
        "agent_id": grant.agent_id,
        "tool_id": grant.tool_id,
        "permission": grant.permission.value,
        "expires_at": grant.expires_at,
        "issued_at": grant.issued_at,
    }


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
        logger.debug("Chat fallback", exc_info=True)
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
        rt.emit_event(EventType.SELF_MOD_STARTED, {
            "intent": req.intent_name,
            "description": req.intent_description,
            "message": f"Designing agent for '{req.intent_name}'...",
        })

        # Auto-approve imports in API mode — user already clicked Build Agent
        async def _auto_approve_imports(names: list[str]) -> bool:
            rt.emit_event(EventType.SELF_MOD_IMPORT_APPROVED, {
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
        if rt._last_execution and (rt.self_mod_manager.was_last_execution_successful() if rt.self_mod_manager else False):
            exec_context = rt.self_mod_manager.format_execution_context() if rt.self_mod_manager else ""

        async def _on_progress(step: str, current: int, total: int) -> None:
            step_labels = {
                "designing": "\u2b21 Designing agent code...",
                "validating": "\u25ce Validating & security scan...",
                "testing": "\u25b3 Sandbox testing...",
                "deploying": "\u25c8 Deploying to mesh...",
            }
            rt.emit_event(EventType.SELF_MOD_PROGRESS, {
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
            # AD-686b: route through Oracle write-path
            oracle = getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)
            semantic_indexed = False
            if oracle is not None:
                semantic_indexed = await oracle.write_semantic(
                    "agent",
                    agent_type=record.agent_type,
                    intent_name=record.intent_name,
                    description=record.intent_name,
                    strategy=record.strategy,
                    source_snippet=record.source_code[:200] if record.source_code else "",
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

            rt.emit_event(EventType.SELF_MOD_SUCCESS, {
                "intent": req.intent_name,
                "agent_type": record.agent_type,
                "agent_id": record.agent_id if hasattr(record, 'agent_id') else record.agent_type,
                "message": success_msg,
                "warnings": warnings,
            })

            # Auto-retry the original request
            if req.original_message:
                rt.emit_event(EventType.SELF_MOD_PROGRESS, {
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
                    rt.emit_event(EventType.SELF_MOD_RETRY_COMPLETE, {
                        "intent": req.intent_name,
                        "response": response,
                        "message": response,
                    })
                except Exception as retry_err:
                    logger.warning("Self-mod retry failed: %s", retry_err)
                    rt.emit_event(EventType.SELF_MOD_RETRY_COMPLETE, {
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
            rt.emit_event(EventType.SELF_MOD_FAILURE, {
                "intent": req.intent_name,
                "message": f"Agent design failed: {error_detail or status}",
                "error": error_detail or status,
            })
    except Exception as e:
        logger.warning("Self-mod pipeline failed: %s", e, exc_info=True)
        rt.emit_event(EventType.SELF_MOD_FAILURE, {
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
