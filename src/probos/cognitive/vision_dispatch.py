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
            data = base64.b64encode(blob).decode("ascii")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": data,
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
