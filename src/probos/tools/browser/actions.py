"""AD-706: Action handlers for BrowserTool's 10-action vocabulary.

Each handler is an async free function that accepts a ``BrowserSession`` and
the action params dict, performs the work via Playwright (or a test fake),
and returns the action's output dict. ``BrowserTool.invoke()`` is a dispatch
table over the action verb that calls into ``dispatch_action``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.tools.browser.session import BrowserSession

logger = logging.getLogger(__name__)


# -- Tier-3 keyword/path heuristics --------------------------------------

_TIER_3_PATH_TOKENS: tuple[str, ...] = (
    "checkout", "payment", "transfer", "subscribe", "signup", "register",
)

_TIER_3_TEXT_RE = re.compile(
    r"i\s+agree|accept\s+(all|cookies|terms)|continue|sign\s*up|"
    r"create\s+account|pay|confirm\s+order|place\s+order|transfer|subscribe",
    re.IGNORECASE,
)


# -- Action dispatch -----------------------------------------------------


async def dispatch_action(
    session: BrowserSession,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a single action to its handler. Raises on unknown action."""
    handler = _HANDLERS.get(action)
    if handler is None:
        raise ValueError(f"unknown browser action: {action}")
    return await handler(session, params)


# -- Individual handlers -------------------------------------------------


async def _action_goto(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    url = params.get("url") or ""
    if not url:
        raise ValueError("goto requires 'url'")
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.goto(url)
    session.set_last_url(url)
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": url,
        "page_title": page_title or "",
    }


async def _action_state(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Return an indexed list of clickable/interactable elements.

    Mirrors the browser-use indexed-element pattern: each entry has a stable
    ``index`` so the LLM can say ``click 5`` instead of synthesizing CSS.
    The session keeps the most recent snapshot so subsequent click/type calls
    can resolve the index back to a selector.
    """
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    elements: list[dict[str, Any]] = []
    if hasattr(page, "list_elements"):
        # Test fake or future deterministic DOM-walk helper.
        try:
            raw = await page.list_elements()
        except Exception:
            logger.debug("AD-706: page.list_elements failed", exc_info=True)
            raw = []
        for i, rec in enumerate(raw or []):
            if not isinstance(rec, dict):
                continue
            entry = {"index": i}
            for key in ("role", "text", "tag", "href", "name", "value", "selector"):
                if key in rec:
                    entry[key] = rec[key]
            elements.append(entry)
    session.record_state_snapshot(elements)
    return {"session_id": session.session_id, "elements": elements}


def _resolve_target_selector(
    session: BrowserSession,
    params: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Resolve params['index'] or params['selector'] to a CSS selector."""
    selector = params.get("selector")
    record: dict[str, Any] | None = None
    if not selector:
        idx = params.get("index")
        if idx is None:
            raise ValueError("click/type requires 'index' or 'selector'")
        if not isinstance(idx, int):
            raise ValueError("'index' must be int")
        record = session.resolve_index(idx)
        if record is None:
            raise ValueError(f"no element at index {idx} in last state snapshot")
        selector = record.get("selector")
        if not selector:
            raise ValueError(f"element at index {idx} has no selector")
    return selector, record


async def _action_click(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector, _record = _resolve_target_selector(session, params)
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.click(selector)
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    url = session.last_url
    if hasattr(page, "url"):
        try:
            page_url = page.url
            if isinstance(page_url, str) and page_url:
                url = page_url
                session.set_last_url(url)
        except Exception:
            logger.debug("AD-706: page.url access failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": url,
        "page_title": page_title or "",
    }


async def _action_type(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector, _record = _resolve_target_selector(session, params)
    text = params.get("text")
    if text is None:
        raise ValueError("type requires 'text'")
    if not isinstance(text, str):
        raise ValueError("'text' must be string")
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    if hasattr(page, "fill"):
        await page.fill(selector, text)
    else:
        await page.type(selector, text)
    return {"session_id": session.session_id, "url": session.last_url}


async def _action_scroll(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    direction = (params.get("direction") or "down").lower()
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError(f"invalid scroll direction: {direction}")
    raw_amount = params.get("amount", 500)
    try:
        amount = int(raw_amount)
    except (TypeError, ValueError):
        raise ValueError("'amount' must be int")
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    dx = 0
    dy = 0
    if direction == "down":
        dy = amount
    elif direction == "up":
        dy = -amount
    elif direction == "right":
        dx = amount
    elif direction == "left":
        dx = -amount
    expr = f"window.scrollBy({dx}, {dy})"
    await page.evaluate(expr)
    return {"session_id": session.session_id, "url": session.last_url}


async def _action_screenshot(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Capture a screenshot, scaled to XGA bounds.

    Anthropic computer-use-demo discipline (MIT): render at
    ``screenshot_max_width × screenshot_max_height`` (default 1024×768) so the
    model gets a token-efficient frame and coordinates remain stable.
    """
    import base64

    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    cfg = session._config  # noqa: SLF001 — same module/package boundary
    max_w = cfg.screenshot_max_width
    max_h = cfg.screenshot_max_height

    # Determine current viewport so we can compute the scale-down factor.
    viewport_w = max_w
    viewport_h = max_h
    try:
        if hasattr(page, "viewport_size"):
            vs = page.viewport_size
            if callable(vs):
                vs = vs()
            if isinstance(vs, dict):
                viewport_w = int(vs.get("width", max_w) or max_w)
                viewport_h = int(vs.get("height", max_h) or max_h)
    except Exception:
        logger.debug("AD-706: viewport_size lookup failed", exc_info=True)

    # Compute target dims preserving aspect ratio, never exceeding XGA bounds.
    if viewport_w > 0 and viewport_h > 0:
        scale = min(max_w / viewport_w, max_h / viewport_h, 1.0)
        out_w = max(1, int(viewport_w * scale))
        out_h = max(1, int(viewport_h * scale))
    else:
        out_w, out_h = max_w, max_h

    raw = await page.screenshot()
    if isinstance(raw, bytes):
        b64 = base64.b64encode(raw).decode("ascii")
    elif isinstance(raw, str):
        b64 = raw
    else:
        b64 = ""
    return {
        "session_id": session.session_id,
        "screenshot_b64": b64,
        "width": out_w,
        "height": out_h,
    }


async def _action_wait(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector = params.get("selector")
    if selector:
        page = session.page
        if page is None:
            raise RuntimeError("browser session is not started")
        await page.wait_for_selector(selector)
        return {"session_id": session.session_id, "waited_for": selector}

    raw_ms = params.get("milliseconds")
    if raw_ms is None:
        raw_seconds = params.get("seconds")
        if raw_seconds is None:
            raise ValueError("wait requires 'milliseconds', 'seconds', or 'selector'")
        ms = int(float(raw_seconds) * 1000)
    else:
        try:
            ms = int(raw_ms)
        except (TypeError, ValueError):
            raise ValueError("'milliseconds' must be int")
    if ms < 0:
        raise ValueError("'milliseconds' must be non-negative")
    t0 = time.monotonic()
    await asyncio.sleep(ms / 1000.0)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    return {"session_id": session.session_id, "waited_ms": elapsed_ms}


async def _action_back(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.go_back()
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": session.last_url,
        "page_title": page_title or "",
    }


async def _action_forward(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.go_forward()
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": session.last_url,
        "page_title": page_title or "",
    }


async def _action_extract_text(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector = params.get("selector") or "body"
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    text = ""
    if hasattr(page, "inner_text"):
        try:
            text = await page.inner_text(selector)
        except Exception:
            logger.debug("AD-706: inner_text failed", exc_info=True)
            text = ""
    return {"session_id": session.session_id, "text": text or ""}


_HANDLERS: dict[str, Any] = {
    "goto": _action_goto,
    "state": _action_state,
    "click": _action_click,
    "type": _action_type,
    "scroll": _action_scroll,
    "screenshot": _action_screenshot,
    "wait": _action_wait,
    "back": _action_back,
    "forward": _action_forward,
    "extract_text": _action_extract_text,
}


# -- AD-706c-1: visual verification via vision tier ----------------------


def _parse_verify_response(raw: str) -> dict[str, Any]:
    """Parse the vision LLM response into ``{ok, observation}``.

    Tier-2 honest-degrade: malformed JSON yields ``ok=None`` plus a clipped
    observation rather than raising. Verification is observability — it
    must never break the action sequence.
    """
    import json as _json
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": None, "observation": "empty vision response"}
    text = raw.strip()
    # Strip code fences if the model wrapped JSON in ``` blocks.
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        payload = _json.loads(text)
    except (ValueError, TypeError):
        return {"ok": None, "observation": text[:200]}
    if not isinstance(payload, dict):
        return {"ok": None, "observation": text[:200]}
    ok = payload.get("ok")
    if not isinstance(ok, bool):
        ok = None
    observation = payload.get("observation", "")
    if not isinstance(observation, str):
        observation = ""
    return {"ok": ok, "observation": observation[:200]}


async def action_verify(
    session: BrowserSession,
    params: dict[str, Any],
    *,
    runtime: Any,
    emit_event: Any,
) -> dict[str, Any]:
    """AD-706c-1: vision-LLM verification of the current page state.

    Returns ``{ok: bool | None, observation: str, screenshot_ref: str | None,
    skipped_reason: str | None}``. Tier-2 honest-degrade: vision tier
    unavailable / unhealthy / call-error returns ``ok=None`` with a
    ``skipped_reason``. NEVER raises — the browser action sequence is
    load-bearing; verification is observational.
    """
    import hashlib as _hashlib
    from probos.events import EventType

    expectation = params.get("expectation", "")
    if not isinstance(expectation, str) or not expectation.strip():
        return {
            "ok": None,
            "observation": "missing expectation",
            "screenshot_ref": None,
            "skipped_reason": "missing_expectation",
        }
    if len(expectation) > 500:
        expectation = expectation[:500]

    page = session.page
    if page is None:
        return {
            "ok": None,
            "observation": "browser session not started",
            "screenshot_ref": None,
            "skipped_reason": "session_not_started",
        }
    try:
        png_bytes = await page.screenshot()
    except Exception:
        logger.warning("AD-706c-1: page.screenshot failed", exc_info=True)
        return {
            "ok": None,
            "observation": "screenshot capture failed",
            "screenshot_ref": None,
            "skipped_reason": "screenshot_error",
        }

    # AD-731: store via AttachmentStore — refs not blobs through any later
    # bus hop. The vision LLM call resolves the ref via the BF-268 OpenAI
    # shape inside ``build_multimodal_messages``.
    try:
        from probos.routers.chat import _get_attachment_store
        store = _get_attachment_store(runtime)
    except Exception:
        logger.warning(
            "AD-706c-1: AttachmentStore lookup failed; skipping verification",
            exc_info=True,
        )
        return {
            "ok": None,
            "observation": "attachment store unavailable",
            "screenshot_ref": None,
            "skipped_reason": "attachment_store_unavailable",
        }

    screenshot_ref = _hashlib.sha256(png_bytes).hexdigest()
    try:
        await store.write(screenshot_ref, png_bytes, "image/png")
    except Exception:
        logger.warning(
            "AD-706c-1: AttachmentStore.write failed; skipping verification",
            exc_info=True,
        )
        return {
            "ok": None,
            "observation": "attachment store write failed",
            "screenshot_ref": None,
            "skipped_reason": "attachment_store_write_error",
        }

    # Vision tier honest-degrade — AD-732 + 10-guard stack.
    try:
        from probos.cognitive.vision_dispatch import is_vision_tier_configured
        cfg = getattr(runtime, "config", None)
        cog_cfg = getattr(cfg, "cognitive", None)
        if cog_cfg is None or not is_vision_tier_configured(cog_cfg, "vision"):
            return {
                "ok": None,
                "observation": "vision tier unconfigured",
                "screenshot_ref": screenshot_ref,
                "skipped_reason": "vision_unconfigured",
            }
    except Exception:
        return {
            "ok": None,
            "observation": "vision tier check failed",
            "screenshot_ref": screenshot_ref,
            "skipped_reason": "vision_check_error",
        }

    prompt_text = (
        f"You are verifying a browser action outcome. The agent expected: "
        f"\"{expectation}\". Look at the screenshot and answer in JSON: "
        f"{{\"ok\": bool, \"observation\": \"<<=200 char description>\"}}. "
        f"Respond with JSON only, no prose."
    )
    raw_response: str = ""
    try:
        from probos.cognitive.vision_dispatch import build_multimodal_messages
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
        request = LLMRequest(
            prompt=prompt_text,
            tier="vision",
            max_tokens=300,
            messages=messages,
        )
        response = await runtime.llm_client.complete(request)
        raw_response = getattr(response, "text", "") or ""
    except Exception:
        logger.warning(
            "AD-706c-1: vision LLM call failed; honest-degrade",
            exc_info=True,
        )
        return {
            "ok": None,
            "observation": "vision tier call failed",
            "screenshot_ref": screenshot_ref,
            "skipped_reason": "vision_unavailable",
        }

    parsed = _parse_verify_response(raw_response)
    parsed["screenshot_ref"] = screenshot_ref
    parsed["skipped_reason"] = None

    if emit_event is not None:
        try:
            emit_event(
                EventType.BROWSER_VERIFY_OBSERVED,
                {
                    "session_id": session.session_id,
                    "expectation": expectation,
                    "ok": parsed["ok"],
                    "screenshot_ref": screenshot_ref,
                    "observation": parsed["observation"],
                },
            )
        except Exception:
            logger.warning(
                "AD-706c-1: emit_event(BROWSER_VERIFY_OBSERVED) failed",
                exc_info=True,
            )
    return parsed


# -- Tier classifier (D6) ------------------------------------------------


# AD-706c-2: register coordinate-aware click handler. Late-bound after
# ``action_verify`` is defined because compute_use reuses it for the Guard
# #9 verification handshake (avoiding a circular import).
from probos.tools.browser.compute_use import action_compute_use_click  # noqa: E402
_HANDLERS["compute_use_click"] = action_compute_use_click


def classify_action(
    session: BrowserSession,
    action: str,
    params: dict[str, Any],
) -> int:
    """Return tier 1, 2, or 3 for the given action.

    * Tier 1 (silent): ``state``, ``screenshot``, ``wait``, ``extract_text``,
      ``scroll``, ``back``, ``forward`` — observation only.
    * Tier 2 (logged-and-proceed): ``goto``, ``click``, ``type`` against
      ordinary domains.
    * Tier 3 (Captain ACK required): ``click`` or ``type`` when host matches
      ``BrowserToolConfig.tier_3_domain_patterns``, OR URL path contains
      checkout/payment/transfer/subscribe/signup/register, OR the clicked
      element's text matches the tier-3 text regex.
    """
    # AD-706c-2: coordinate-aware click is always tier-3 (destructive click
    # at an unverified pixel coordinate). Captain ACK required every call.
    # Checked BEFORE the silent/goto bands so AD-706e's later additive
    # always-tier-3 entries can stack without re-shaping this branch.
    if action == "compute_use_click":
        return 3
    silent = {"state", "screenshot", "wait", "extract_text", "scroll", "back", "forward", "verify"}
    if action in silent:
        return 1
    if action == "goto":
        return 2
    if action not in {"click", "type"}:
        return 2

    # Click / type: inspect URL + element text for tier-3 indicators.
    cfg = session._config  # noqa: SLF001
    url = params.get("url") or session.last_url or ""
    host, path = _split_url(url)
    if _host_matches_tier_3(host, cfg.tier_3_domain_patterns):
        return 3
    if path and any(token in path.lower() for token in _TIER_3_PATH_TOKENS):
        return 3

    # Inspect the element from the most recent state() snapshot, if available.
    record: dict[str, Any] | None = None
    selector = params.get("selector")
    if selector is None:
        idx = params.get("index")
        if isinstance(idx, int):
            record = session.resolve_index(idx)
    if record is not None:
        text = record.get("text") or ""
        if isinstance(text, str) and _TIER_3_TEXT_RE.search(text):
            return 3
    return 2


def _split_url(url: str) -> tuple[str, str]:
    """Return (host, path) from a URL string. Empty strings on parse failure."""
    if not url:
        return "", ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return (parsed.hostname or "").lower(), parsed.path or ""
    except Exception:
        return "", ""


def _host_matches_tier_3(host: str, patterns: list[str]) -> bool:
    if not host or not patterns:
        return False
    import fnmatch

    host_lower = host.lower()
    for pat in patterns:
        if not isinstance(pat, str) or not pat:
            continue
        if fnmatch.fnmatchcase(host_lower, pat.lower()):
            return True
    return False
