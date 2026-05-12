"""AD-720d (Wave 139): vision pipe-through dispatch.

Builds the OpenAI/Anthropic-shape multimodal ``messages`` array from a user
prompt + a list of attachment_ids. Pure formatter — does not call the LLM
client; the caller decides routing based on whether the array contains image
content items.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from probos.attachments.store import AttachmentStore
from probos.cognitive.text_extractor import extract_text

logger = logging.getLogger(__name__)


_PDF_DEFERRED_NOTE = "PDF extraction not yet wired (AD-720a-1)"


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
    # AD-731: observability — log the wire size for vision DMs so the
    # ~70-bytes-per-ref invariant is visible in logs (versus 150 KB-1 MB
    # for the old inline-base64 shape).
    if image_ids:
        import json as _json
        wire_size = len(_json.dumps(messages))
        logger.info(
            "AD-731: emitting %d attachment_ref block(s) for vision DM "
            "(total wire size ~%d bytes)",
            len(image_ids), wire_size,
        )
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
