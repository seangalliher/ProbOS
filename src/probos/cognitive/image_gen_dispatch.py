"""AD-730-3: agent image generation via OpenAI-compatible Images API.

Sixth peer tier (image_gen) handler. Mirrors vision_dispatch shape:
honest-degrade constants, configuration probe, request adapter.

Critical invariants:
  * AD-731 — bytes flow through ``AttachmentStore.write(sha, blob, mime)``.
    Source-scan asserts no inline base64 in the bus or response shape.
  * BF-269 — does NOT participate in fast→standard→deep fallback.
  * BF-272 — bypasses ``LLMResponseCache`` (image bytes are non-cacheable).
  * BF-273 — bypasses ``ModelRouter`` (router only knows text tiers).
  * AD-727 — first invocation per agent emits a Counselor wellness
    review log line.
  * AD-541b — successful image gen writes an anchored, high-importance
    episode so future recall cannot hallucinate a non-existent image.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


IMAGE_GEN_UNCONFIGURED_MESSAGE = (
    "(image generation unavailable — operator has not configured the "
    "image_gen tier; the [GEN_IMAGE ...] marker was stripped)"
)
IMAGE_GEN_DISABLED_MESSAGE = (
    "(image generation disabled — AvatarsConfig.image_gen_enabled is False)"
)
IMAGE_GEN_FAILED_MESSAGE = (
    "(image generation failed — endpoint returned an error; reply preserved "
    "without image)"
)
IMAGE_GEN_TOO_LARGE_MESSAGE = (
    "(image generation rejected — returned bytes exceeded the "
    "AvatarsConfig.image_gen_max_image_bytes cap)"
)


# Process-scoped set of agent IDs that have already triggered a wellness
# review log line. Intentionally NOT persisted — restart resets by design.
_WELLNESS_REVIEW_SEEN: set[str] = set()


def is_image_gen_tier_configured(cognitive_cfg: Any) -> bool:
    """Mirror ``is_vision_tier_configured``: True iff base_url AND model
    are non-empty strings on the cognitive config block.
    """
    base = getattr(cognitive_cfg, "llm_base_url_image_gen", None)
    model = getattr(cognitive_cfg, "llm_model_image_gen", None)
    return bool(base) and bool(model)


def _maybe_emit_wellness_review(runtime: Any, agent_id: str) -> None:
    """AD-727: first image_gen call per agent per process triggers a
    Counselor wellness review log line. Subsequent calls are no-op.

    Process-scoped — intentionally NOT persisted. Restart resets the
    review interval. Suitable for v1 governance signal; persistent
    dedupe is a forward marker (AD-730-3-1).
    """
    if agent_id in _WELLNESS_REVIEW_SEEN:
        return
    _WELLNESS_REVIEW_SEEN.add(agent_id)
    logger.warning(
        "AD-727/AD-730-3 WELLNESS REVIEW: agent=%s has invoked image "
        "generation for the first time this process; counselor should "
        "review capability use during next scheduled wellness check",
        agent_id,
    )


async def _maybe_write_anchored_episode(
    runtime: Any,
    *,
    agent_id: str,
    sha: str,
    mime: str,
    prompt: str,
) -> None:
    """AD-541b: write a high-importance anchored episode on success so
    future recall cannot confabulate that the agent produced an image
    when none was actually generated. Never raises.
    """
    try:
        episodic = getattr(runtime, "episodic_memory", None)
        if episodic is None or not hasattr(episodic, "store_episode"):
            return
        await episodic.store_episode(
            agent_id=agent_id,
            content=(
                f"Generated image (sha={sha[:12]}) for prompt: {prompt[:160]}"
            ),
            importance=8,
            metadata={
                "anchored": True,
                "ad": "AD-730-3",
                "attachment_id": sha,
                "mime": mime,
            },
        )
    except Exception:
        logger.warning(
            "AD-730-3: anchored episode write failed for agent=%s sha=%s",
            agent_id, sha[:12], exc_info=True,
        )


async def dispatch_image_gen(
    runtime: Any,
    *,
    agent_id: str,
    prompt: str,
) -> dict[str, Any]:
    """Generate an image, persist to AttachmentStore, return attachment_id.

    Returns a flat dict:
      * Success: ``{"ok": True, "attachment_id": str, "mime": str,
        "size_bytes": int, "prompt": str}``.
      * Honest-degrade: ``{"ok": False, "reason": str, "message": str}``.

    NEVER raises. ModelRouter bypassed; cache bypassed; no fallback to
    text tiers (BF-269/BF-272/BF-273).
    """
    cfg_root = getattr(runtime, "config", None)
    cog_cfg = getattr(cfg_root, "cognitive", None)
    av_cfg = getattr(cfg_root, "avatars", None)

    if not bool(getattr(av_cfg, "image_gen_enabled", False)):
        return {
            "ok": False,
            "reason": "image_gen_disabled",
            "message": IMAGE_GEN_DISABLED_MESSAGE,
        }
    if not is_image_gen_tier_configured(cog_cfg):
        return {
            "ok": False,
            "reason": "image_gen_unconfigured",
            "message": IMAGE_GEN_UNCONFIGURED_MESSAGE,
        }

    if bool(getattr(av_cfg, "image_gen_wellness_review_required", True)):
        _maybe_emit_wellness_review(runtime, agent_id)

    tc = cog_cfg.tier_config("image_gen")
    base_url = str(tc["base_url"]).rstrip("/")
    api_key = tc.get("api_key") or ""
    model = tc["model"]
    timeout_s = float(tc.get("timeout") or 60.0)

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url}/images/generations"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception:
        logger.warning(
            "AD-730-3: image_gen endpoint call raised for agent=%s",
            agent_id, exc_info=True,
        )
        return {
            "ok": False,
            "reason": "transport_error",
            "message": IMAGE_GEN_FAILED_MESSAGE,
        }

    if resp.status_code >= 400:
        logger.warning(
            "AD-730-3: image_gen endpoint returned %d for agent=%s body=%s",
            resp.status_code, agent_id, resp.text[:512],
        )
        return {
            "ok": False,
            "reason": f"http_{resp.status_code}",
            "message": IMAGE_GEN_FAILED_MESSAGE,
        }

    try:
        data = resp.json()
        b64 = data["data"][0]["b64_json"]
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        logger.warning(
            "AD-730-3: image_gen response parse failed for agent=%s",
            agent_id, exc_info=True,
        )
        return {
            "ok": False,
            "reason": "parse_error",
            "message": IMAGE_GEN_FAILED_MESSAGE,
        }

    max_bytes = int(getattr(av_cfg, "image_gen_max_image_bytes", 4 * 1024 * 1024))
    if len(blob) > max_bytes:
        return {
            "ok": False,
            "reason": "too_large",
            "message": IMAGE_GEN_TOO_LARGE_MESSAGE,
        }

    sha = hashlib.sha256(blob).hexdigest()
    mime = str(getattr(av_cfg, "image_gen_mime", "image/png"))
    store = getattr(runtime, "attachment_store", None)
    if store is None:
        return {
            "ok": False,
            "reason": "store_unavailable",
            "message": IMAGE_GEN_FAILED_MESSAGE,
        }

    try:
        await store.write(sha, blob, mime)
    except Exception:
        logger.warning(
            "AD-730-3: AttachmentStore.write failed for agent=%s sha=%s",
            agent_id, sha[:12], exc_info=True,
        )
        return {
            "ok": False,
            "reason": "store_write_error",
            "message": IMAGE_GEN_FAILED_MESSAGE,
        }

    # AD-541b: anchored episode for memory integrity.
    await _maybe_write_anchored_episode(
        runtime, agent_id=agent_id, sha=sha, mime=mime, prompt=prompt,
    )

    return {
        "ok": True,
        "attachment_id": sha,
        "mime": mime,
        "size_bytes": len(blob),
        "prompt": prompt,
    }
