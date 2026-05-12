"""AD-720d (Wave 139): vision pipe-through dispatch.

Builds the OpenAI/Anthropic-shape multimodal ``messages`` array from a user
prompt + a list of attachment_ids. Pure formatter — does not call the LLM
client; the caller decides routing based on whether the array contains image
content items.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Awaitable, Callable

from probos.attachments.store import AttachmentStore
from probos.cognitive.text_extractor import extract_text

logger = logging.getLogger(__name__)


_PDF_DEFERRED_NOTE = "PDF extraction not yet wired (AD-720a-1)"


# AD-732: Operator-facing honest-degrade messages. Two variants because they
# have different remediations — "unconfigured" needs setup; "unhealthy" needs
# the endpoint restarted. The /api/chat and /api/agent/{id}/chat handlers
# both return one of these (no LLM call, no intent dispatch) instead of the
# pre-AD-732 "Try again in a moment" stub, which was misleading on a
# permanently-misconfigured instance.
#
# BF-274 (2026-05-12): RESTORED after accidental removal during BF-273-DIAG
# revert. The agent_chat handler imports these by name; without them in this
# module, every vision DM hit ImportError inside the try/except wrap and fell
# through to the text path silently. The "agent_chat attachment augmentation
# failed: ImportError" warning was logged, but the user-facing failure looked
# like the agent simply couldn't see images.
VISION_UNCONFIGURED_MESSAGE = (
    "Vision LLM is not configured on this ProbOS instance. Image attachments "
    "require a vision-capable model. To enable it, install Ollama "
    "(https://ollama.com), run `ollama pull qwen3.6:27b`, then uncomment the "
    "vision tier block in config/system.yaml. Alternatively, point "
    "cognitive.llm_base_url_vision and cognitive.llm_model_vision at "
    "OpenAI, Anthropic, or any other OpenAI-compatible vision endpoint."
)

VISION_UNHEALTHY_MESSAGE = (
    "Vision LLM endpoint is configured but currently unreachable. "
    "Check that the configured vision endpoint (cognitive.llm_base_url_vision) "
    "is running and reachable. Once the endpoint recovers, image attachments "
    "will work again on the next message."
)


def is_vision_tier_configured(cfg: Any, tier_name: str) -> bool:
    """AD-732: vision tier is "configured" iff it has both a model name AND
    a non-default base URL on the CognitiveConfig.

    The empty-string ``llm_model_vision`` sentinel (and ``None``) both mean
    unconfigured; operators must set both ``llm_base_url_vision`` and
    ``llm_model_vision`` to enable the vision tier.

    When the configured ``tier_name`` is one of the legacy tiers ("fast",
    "standard", "deep"), return True — those tiers are always configured by
    default (they fall back to the shared ``llm_base_url`` if no per-tier
    override is set). Only "vision" requires the explicit configured-check
    because it is opt-in by default (see AttachmentsConfig.vision_tier).
    """
    if tier_name != "vision":
        return True
    model = getattr(cfg, "llm_model_vision", None) or ""
    base_url = getattr(cfg, "llm_base_url_vision", None)
    return bool(model and base_url)


def resolve_vision_tier_for_agent(
    attach_cfg: Any, agent_type: str, default_tier: str
) -> str:
    """AD-730-5: resolve the vision tier for a specific agent_type.

    Returns the override from ``attach_cfg.vision_tier_overrides[agent_type]``
    when present; otherwise ``default_tier``. Pure function — no side effects,
    no LLM client lookup. Health-validation (does the resolved tier exist
    in the LLM client?) is the caller's responsibility (tier-2 log-and-degrade
    pattern at the dispatch site).

    An empty ``agent_type`` (no agent context — e.g. untargeted captain
    chat) short-circuits to ``default_tier`` without dict lookup.
    """
    if not agent_type:
        return default_tier
    overrides = getattr(attach_cfg, "vision_tier_overrides", None) or {}
    return overrides.get(agent_type, default_tier)


async def _resolve_one(
    attachment_id: str,
    store: AttachmentStore,
    mime_lookup: Callable[[str], Awaitable[str | None]],
    text_extraction_max_bytes: int,
    pdf_extraction_enabled: bool,
) -> tuple[str | None, bytes | None, dict[str, Any] | None]:
    """Resolve an attachment to its (mime, blob, content_item) tuple.

    Returns ``(mime, blob, content_item)``. ``content_item`` is None when the
    attachment is an image (caller composes the image content item itself,
    avoiding a redundant base64-encode in the failure case).

    On failure (FileNotFoundError, mime lookup miss): logs warning and returns
    a ``failed_to_load`` text content item. Tier-2 log-and-degrade — never
    silent drop, never raise.
    """
    try:
        mime = await mime_lookup(attachment_id)
        if mime is None:
            logger.warning(
                "AD-720d attachment lookup failed (no mime for %s); "
                "emitting failed_to_load stub",
                attachment_id,
            )
            return (
                None,
                None,
                {
                    "type": "text",
                    "text": (
                        f'<ATTACHMENT id="{attachment_id}" '
                        f'note="failed_to_load" />'
                    ),
                },
            )
        blob = await store.read(attachment_id)
        return (mime, blob, None)
    except FileNotFoundError:
        logger.warning(
            "AD-720d attachment %s not found on disk; emitting failed_to_load stub",
            attachment_id,
        )
        return (
            None,
            None,
            {
                "type": "text",
                "text": (
                    f'<ATTACHMENT id="{attachment_id}" '
                    f'note="failed_to_load" />'
                ),
            },
        )


async def build_multimodal_messages(
    prompt: str,
    attachment_ids: list[str],
    store: AttachmentStore,
    mime_lookup: Callable[[str], Awaitable[str | None]],
    *,
    text_extraction_max_bytes: int,
    pdf_extraction_enabled: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build the OpenAI/Anthropic-shape ``messages`` content array.

    Returns ``(messages, image_attachment_ids)`` where ``messages`` is the
    one-element list ``[{"role": "user", "content": [<content_items>]}]`` and
    ``image_attachment_ids`` is the subset of ``attachment_ids`` whose MIME is
    ``image/*``. The caller uses ``image_attachment_ids`` to decide whether
    the turn routes via the vision tier (image present) or whether the
    augmented prompt flows through the standard decomposer (text-only).
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    image_ids: list[str] = []

    resolved = await asyncio.gather(
        *(
            _resolve_one(
                aid, store, mime_lookup,
                text_extraction_max_bytes, pdf_extraction_enabled,
            )
            for aid in attachment_ids
        )
    )

    for attachment_id, (mime, blob, failure_item) in zip(attachment_ids, resolved):
        if failure_item is not None:
            content.append(failure_item)
            continue
        assert mime is not None and blob is not None  # narrow the optional

        if mime.startswith("image/"):
            image_ids.append(attachment_id)
            # AD-731: emit a content-addressable ref instead of inline base64.
            # The receiver dereferences from the local AttachmentStore inside
            # the LLM client immediately before the HTTP POST. This keeps the
            # bus message ~70 bytes per image instead of 150 KB-1 MB and
            # restores the uniform-NATS-transport invariant (AD-637z2).
            #
            # BF-278 (2026-05-12): RESTORED after accidental regression in
            # BF-274. When BF-274 restored VISION_UNCONFIGURED_MESSAGE et al.,
            # the working tree's ``vision_dispatch.py`` had ALSO reverted the
            # AD-731 ref-shape emission back to inline-base64 with Anthropic-
            # source-shape. The bus carried that shape through, the resolver
            # ``_resolve_attachment_refs_for_openai`` only matches blocks
            # whose source.type=="attachment_ref" so it left them untouched,
            # and Ollama qwen3.6:27b rejected the resulting Anthropic-shape
            # payload with HTTP 400 "invalid message format". Captured live
            # via tmp_capture_proxy.py 2026-05-12.
            content.append({
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": attachment_id,
                    "media_type": mime,
                },
            })
            continue

        if mime == "application/pdf" and not pdf_extraction_enabled:
            content.append({
                "type": "text",
                "text": (
                    f'<ATTACHMENT id="{attachment_id}" mime="application/pdf" '
                    f'note="{_PDF_DEFERRED_NOTE}" />'
                ),
            })
            continue

        try:
            text, _truncated = await extract_text(
                blob, mime, max_bytes=text_extraction_max_bytes,
            )
        except NotImplementedError:
            # PDF with extraction enabled but not yet wired — emit the stub.
            logger.warning(
                "AD-720d text extraction not implemented for mime=%s "
                "(attachment_id=%s); emitting deferred-feature stub",
                mime, attachment_id,
            )
            content.append({
                "type": "text",
                "text": (
                    f'<ATTACHMENT id="{attachment_id}" mime="{mime}" '
                    f'note="{_PDF_DEFERRED_NOTE}" />'
                ),
            })
            continue
        except (UnicodeDecodeError, ValueError) as e:
            logger.warning(
                "AD-720d text extraction failed for attachment_id=%s mime=%s: %s",
                attachment_id, mime, e,
            )
            content.append({
                "type": "text",
                "text": (
                    f'<ATTACHMENT id="{attachment_id}" mime="{mime}" '
                    f'note="extraction_failed" />'
                ),
            })
            continue

        content.append({
            "type": "text",
            "text": (
                f'<ATTACHMENT id="{attachment_id}" mime="{mime}">\n'
                f'{text}\n'
                f'</ATTACHMENT>'
            ),
        })

    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
    return (messages, image_ids)


async def augment_prompt_with_attachment_text(
    prompt: str,
    attachment_ids: list[str],
    store: AttachmentStore,
    mime_lookup: Callable[[str], Awaitable[str | None]],
    *,
    text_extraction_max_bytes: int,
    pdf_extraction_enabled: bool,
) -> str:
    """Return ``prompt`` augmented with text content extracted from non-image
    attachments and inline markers for image attachments.

    Used by the @callsign-DM path in /api/chat and by /api/agent/{id}/chat
    where the receiving agent's prompt assembly is text-only (no vision).
    For image attachments we emit ``[Captain attached an image (id=...)]``
    so the agent can at least acknowledge the attachment in its reply.
    Tier-2 log-and-degrade: on any failure returns the original prompt.
    """
    if not attachment_ids:
        return prompt
    try:
        messages, image_ids = await build_multimodal_messages(
            prompt=prompt,
            attachment_ids=list(attachment_ids),
            store=store,
            mime_lookup=mime_lookup,
            text_extraction_max_bytes=text_extraction_max_bytes,
            pdf_extraction_enabled=pdf_extraction_enabled,
        )
    except Exception as e:
        logger.warning(
            "Attachment augmentation failed; sending text-only prompt. "
            "attachment_ids=%s err=%s: %s",
            list(attachment_ids), type(e).__name__, e,
        )
        return prompt
    parts: list[str] = [prompt] if prompt else []
    for iid in image_ids:
        parts.append(f"[Captain attached an image (id={iid})]")
    for item in messages[0]["content"]:
        if item.get("type") == "text" and item.get("text") and item.get("text") != prompt:
            parts.append(item["text"])
    return "\n\n".join(p for p in parts if p)
