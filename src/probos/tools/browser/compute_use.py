"""AD-706c-2: coordinate-aware ``compute_use_click`` BrowserTool action.

For DOM-less surfaces (HTML5 canvas, embedded VNC, screenshot-only PDFs)
where ``state()`` returns no interactable elements. Captures a screenshot,
asks a coordinate-prediction LLM tier (``compute_use``) where to click,
runs a vision-verification handshake against the same screenshot via
AD-706c-1's ``action_verify``, then executes ``page.mouse.click(x, y)``
only if verification agrees.

Ten guards inherited from AD-732 + BF-268..273 stack, plus two new:
* Guard #9 — coordinate verification handshake (AD-706c-1 ``verify`` reuse).
* Guard #10 — per-session trust budget (consecutive-autonomous + total caps).

Always tier-3 (see classify_action in actions.py). Captain ACK required for
every call. No cache (BF-272: time-dependent screenshots), no fallback chain
(BF-269: text tiers can't see images).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from probos.cognitive.vision_dispatch import (
    VISION_UNCONFIGURED_MESSAGE,
    build_multimodal_messages,
    is_vision_tier_configured,
)
# AD-731 invariant: refs not blobs. ``build_multimodal_messages`` builds the
# OpenAI-shape multimodal payload; the LLM client's
# ``_resolve_attachment_refs_for_openai`` (llm_client.py:783) resolves SHA-256
# refs to ``image_url`` data URIs before POST. BF-268 lesson: Ollama and
# OpenAI-compat endpoints all speak the OpenAI shape, NOT the Anthropic
# multimodal envelope.
from probos.events import EventType
from probos.tools.browser.session import BrowserSession

logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE = (
    "You are a coordinate-prediction assistant for a browser automation agent. "
    "The agent wants to click an element described as: {intent!r}. "
    "Look at the screenshot and reply with JSON ONLY (no prose, no code fence): "
    '{{"x": <int>, "y": <int>, "confidence": <float between 0 and 1>}}. '
    "Coordinates are in screenshot pixels with (0,0) at the top-left."
)


def _parse_coordinate_response(raw: str) -> dict[str, Any] | None:
    """Parse the compute_use LLM response into ``{x, y, confidence}``.

    Returns None on any parse failure — caller honest-degrades with
    ``skipped_reason="parse_error"``.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        x = int(payload["x"])
        y = int(payload["y"])
    except (KeyError, TypeError, ValueError):
        return None
    confidence = payload.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    return {"x": x, "y": y, "confidence": confidence}


async def action_compute_use_click(
    session: BrowserSession,
    params: dict[str, Any],
    *,
    runtime: Any,
    emit_event: Any,
) -> dict[str, Any]:
    """AD-706c-2: predict click coordinates from a screenshot, verify, execute.

    Returns ``{ok: bool, x, y, confidence, verified, skipped_reason}``.
    Tier-2 honest-degrade on every failure mode: NEVER raises. Always
    classified tier-3 (Captain ACK required) by ``classify_action``.
    """
    intent_raw = params.get("intent", "")
    if not isinstance(intent_raw, str) or not intent_raw.strip():
        return {
            "ok": False,
            "skipped_reason": "missing_intent",
            "message": "compute_use_click requires a non-empty 'intent' parameter",
        }
    intent = intent_raw.strip()[:500]

    # Guard: tier configuration — REUSE vision_dispatch helpers (BF-274 lesson).
    cfg = getattr(runtime, "config", None)
    cog_cfg = getattr(cfg, "cognitive", None)
    if cog_cfg is None or not is_vision_tier_configured(cog_cfg, "compute_use"):
        return {
            "ok": False,
            "skipped_reason": "compute_use_unconfigured",
            "message": VISION_UNCONFIGURED_MESSAGE,
        }

    # Guard #10: trust budget.
    browser_tool_cfg = getattr(cfg, "browser_tool", None)
    if browser_tool_cfg is None:
        return {
            "ok": False,
            "skipped_reason": "browser_config_missing",
            "message": "Browser tool configuration unavailable",
        }
    max_consec = int(getattr(browser_tool_cfg, "compute_use_max_consecutive_autonomous_actions", 5))
    max_total = int(getattr(browser_tool_cfg, "compute_use_max_per_session", 50))
    if max_consec > 0 and session.compute_use_consecutive_autonomous >= max_consec:
        return {
            "ok": False,
            "skipped_reason": "trust_budget_exhausted",
            "message": (
                f"compute_use trust budget exhausted: "
                f"{session.compute_use_consecutive_autonomous} consecutive "
                f"autonomous calls (cap {max_consec}). Captain ACK required."
            ),
        }
    if max_total > 0 and session.compute_use_total_calls >= max_total:
        return {
            "ok": False,
            "skipped_reason": "trust_budget_exhausted",
            "message": (
                f"compute_use per-session budget exhausted: "
                f"{session.compute_use_total_calls}/{max_total} calls."
            ),
        }

    page = session.page
    if page is None:
        return {
            "ok": False,
            "skipped_reason": "session_not_started",
            "message": "browser session not started",
        }

    # Screenshot capture.
    try:
        png_bytes = await page.screenshot()
    except Exception:
        logger.warning("AD-706c-2: page.screenshot failed", exc_info=True)
        return {
            "ok": False,
            "skipped_reason": "screenshot_error",
            "message": "screenshot capture failed",
        }

    # AD-731: refs not blobs — write to AttachmentStore keyed by SHA-256.
    try:
        from probos.routers.chat import _get_attachment_store
        store = _get_attachment_store(runtime)
    except Exception:
        logger.warning("AD-706c-2: AttachmentStore lookup failed", exc_info=True)
        return {
            "ok": False,
            "skipped_reason": "attachment_store_unavailable",
            "message": "attachment store unavailable",
        }
    screenshot_ref = hashlib.sha256(png_bytes).hexdigest()
    try:
        await store.write(screenshot_ref, png_bytes, "image/png")
    except Exception:
        logger.warning("AD-706c-2: AttachmentStore.write failed", exc_info=True)
        return {
            "ok": False,
            "skipped_reason": "attachment_store_write_error",
            "message": "attachment store write failed",
        }

    # LLM call: compute_use tier, NO cache (BF-272), NO fallback chain (BF-269).
    prompt_text = _PROMPT_TEMPLATE.format(intent=intent)
    try:
        from probos.cognitive.llm_client import LLMRequest

        attach_cfg = getattr(cfg, "attachments", None)
        text_max = int(getattr(attach_cfg, "text_extraction_max_bytes", 32768))
        pdf_on = bool(getattr(attach_cfg, "pdf_extraction_enabled", False))

        async def _mime_lookup(_aid: str) -> str | None:
            return "image/png"

        messages, _image_ids, _per = await build_multimodal_messages(
            prompt=prompt_text,
            attachment_ids=[screenshot_ref],
            store=store,
            mime_lookup=_mime_lookup,
            text_extraction_max_bytes=text_max,
            pdf_extraction_enabled=pdf_on,
        )
        max_tokens = int(getattr(cog_cfg, "llm_max_tokens_compute_use", None) or 256)
        request = LLMRequest(
            prompt=prompt_text,
            tier="compute_use",
            max_tokens=max_tokens,
            messages=messages,
        )
        response = await runtime.llm_client.complete(request)
        raw_response = getattr(response, "text", "") or ""
    except Exception:
        logger.warning("AD-706c-2: compute_use LLM call failed", exc_info=True)
        # Increment counters even on failure — quota is per attempt, not per success
        session.note_compute_use_call()
        return {
            "ok": False,
            "skipped_reason": "compute_use_unavailable",
            "message": "compute_use tier call failed",
        }

    parsed = _parse_coordinate_response(raw_response)
    if parsed is None:
        session.note_compute_use_call()
        return {
            "ok": False,
            "skipped_reason": "parse_error",
            "message": "compute_use response was not parseable JSON",
        }
    x, y, confidence = parsed["x"], parsed["y"], parsed["confidence"]

    if emit_event is not None:
        try:
            emit_event(
                EventType.BROWSER_COMPUTE_USE_CLICK_PROPOSED,
                {
                    "session_id": session.session_id,
                    "intent": intent,
                    "x": x,
                    "y": y,
                    "confidence": confidence,
                    "screenshot_ref": screenshot_ref,
                },
            )
        except Exception:
            logger.warning(
                "AD-706c-2: emit_event(CLICK_PROPOSED) failed", exc_info=True
            )

    # Guard #9: coordinate verification handshake. Reuse AD-706c-1's
    # action_verify — never fork. Late import to avoid the actions.py <-> compute_use.py
    # circular-import surface (actions.py imports this module at module load).
    from probos.tools.browser.actions import action_verify
    verify_expectation = (
        f"the element described as {intent!r} is visible near coordinate ({x}, {y})"
    )
    try:
        verify_result = await action_verify(
            session,
            {"expectation": verify_expectation},
            runtime=runtime,
            emit_event=emit_event,
        )
    except Exception:
        logger.warning("AD-706c-2: verify handshake raised", exc_info=True)
        session.note_compute_use_call()
        return {
            "ok": False,
            "skipped_reason": "verification_error",
            "message": "verify handshake failed",
            "x": x,
            "y": y,
            "confidence": confidence,
        }
    verify_ok = verify_result.get("ok")
    if verify_ok is not True:
        session.note_compute_use_call()
        if emit_event is not None:
            try:
                emit_event(
                    EventType.BROWSER_COMPUTE_USE_CLICK_ABORTED,
                    {
                        "session_id": session.session_id,
                        "intent": intent,
                        "x": x,
                        "y": y,
                        "verify_ok": verify_ok,
                        "verify_observation": verify_result.get("observation", ""),
                    },
                )
            except Exception:
                logger.warning(
                    "AD-706c-2: emit_event(CLICK_ABORTED) failed", exc_info=True
                )
        return {
            "ok": False,
            "skipped_reason": "verification_failed",
            "message": "verification handshake disagreed with predicted coordinate",
            "x": x,
            "y": y,
            "confidence": confidence,
            "verified": False,
            "verify_observation": verify_result.get("observation", ""),
        }

    if emit_event is not None:
        try:
            emit_event(
                EventType.BROWSER_COMPUTE_USE_CLICK_VERIFIED,
                {
                    "session_id": session.session_id,
                    "intent": intent,
                    "x": x,
                    "y": y,
                },
            )
        except Exception:
            logger.warning(
                "AD-706c-2: emit_event(CLICK_VERIFIED) failed", exc_info=True
            )

    # Execute the click.
    try:
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            raise RuntimeError("page has no mouse handle")
        await mouse.click(x, y)
    except Exception:
        logger.warning("AD-706c-2: page.mouse.click failed", exc_info=True)
        session.note_compute_use_call()
        return {
            "ok": False,
            "skipped_reason": "click_error",
            "message": "page.mouse.click failed",
            "x": x,
            "y": y,
            "confidence": confidence,
            "verified": True,
        }

    session.note_compute_use_call()
    if emit_event is not None:
        try:
            emit_event(
                EventType.BROWSER_COMPUTE_USE_CLICK_EXECUTED,
                {
                    "session_id": session.session_id,
                    "intent": intent,
                    "x": x,
                    "y": y,
                    "confidence": confidence,
                },
            )
        except Exception:
            logger.warning(
                "AD-706c-2: emit_event(CLICK_EXECUTED) failed", exc_info=True
            )
    return {
        "ok": True,
        "x": x,
        "y": y,
        "confidence": confidence,
        "verified": True,
        "screenshot_ref": screenshot_ref,
        "skipped_reason": None,
    }
