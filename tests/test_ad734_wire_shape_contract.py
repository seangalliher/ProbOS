"""AD-734 — Wire-shape contract test for the vision pipeline.

Codifies the live-capture work done with ``tmp_capture_proxy.py`` during the
BF-268 / BF-278 debug arc as a CI-runnable pytest. Pins the exact JSON shape
on both sides of the LLM-bound boundary so silent regressions (like the one
that rode along uncaught through BF-274) are caught at commit time.

The three asserted invariants:

1. ``build_multimodal_messages`` emits the **bus shape**:
   ``{"type": "image", "source": {"type": "attachment_ref",
                                  "sha256": <hex>, "media_type": <mime>}}``
   — NEVER inline base64, NEVER Anthropic ``source.base64``.

2. ``OpenAICompatibleClient._resolve_attachment_refs_for_openai`` rewrites
   that to the **OpenAI chat-completions vision shape**:
   ``{"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}``
   — NEVER carries the ``attachment_ref`` source forward, NEVER emits the
   Anthropic ``source.base64`` shape that the Copilot proxy silently drops.

3. End-to-end ``_call_openai`` POSTs a payload whose ``messages[*].content``
   contains the OpenAI ``image_url`` block — captured via ``httpx.MockTransport``,
   the same observation tmp_capture_proxy.py made live on 2026-05-12.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.attachments.store import AttachmentStore
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.vision_dispatch import build_multimodal_messages
from probos.types import LLMRequest


# A 1x1 PNG (smallest valid). Bytes captured from a hex literal so the test
# has zero filesystem dependencies.
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63f8cfc0500f0000030101005f3a8e740000000049454e44ae426082"
)


class _InMemoryAttachmentStore:
    """Minimal AttachmentStore (Protocol) implementation for testing."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._mimes: dict[str, str] = {}

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        self._blobs[content_hash] = blob
        self._mimes[content_hash] = mime
        return Path(f"/mem/{content_hash}")

    async def read(self, content_hash: str) -> bytes:
        if content_hash not in self._blobs:
            raise FileNotFoundError(content_hash)
        return self._blobs[content_hash]

    async def exists(self, content_hash: str) -> bool:
        return content_hash in self._blobs

    async def get_path(self, content_hash: str) -> Path:
        return Path(f"/mem/{content_hash}")

    async def size(self, content_hash: str) -> int:
        return len(self._blobs[content_hash])


async def _mime_lookup_png(_aid: str) -> str | None:
    return "image/png"


@pytest.fixture
def store_with_png() -> tuple[_InMemoryAttachmentStore, str]:
    store = _InMemoryAttachmentStore()
    sha = hashlib.sha256(_PNG_1X1).hexdigest()
    # Schedule the seed on the running loop synchronously via asyncio.run
    # is not safe inside pytest-asyncio; tests below do the write themselves
    # if they need fresh state. Here we just precompute hash + return store.
    store._blobs[sha] = _PNG_1X1
    store._mimes[sha] = "image/png"
    return store, sha


@pytest.mark.asyncio
async def test_build_multimodal_messages_emits_attachment_ref_bus_shape(
    store_with_png: tuple[_InMemoryAttachmentStore, str],
) -> None:
    """Invariant #1 — sender emits the content-addressable bus shape."""
    store, sha = store_with_png

    messages, image_ids, _per_attachment = await build_multimodal_messages(
        prompt="describe this",
        attachment_ids=[sha],
        store=store,  # type: ignore[arg-type]
        mime_lookup=_mime_lookup_png,
        text_extraction_max_bytes=4096,
        pdf_extraction_enabled=False,
    )

    assert image_ids == [sha]
    assert len(messages) == 1
    content = messages[0]["content"]
    image_blocks = [b for b in content if b.get("type") == "image"]
    assert len(image_blocks) == 1, "exactly one image block expected"
    block = image_blocks[0]

    # Required shape — the AD-731 invariant.
    assert block == {
        "type": "image",
        "source": {
            "type": "attachment_ref",
            "sha256": sha,
            "media_type": "image/png",
        },
    }

    # Forbidden shapes (regression guards).
    serialized = json.dumps(messages)
    assert "base64" not in serialized, (
        "bus must NOT carry inline base64 — content-addressable refs only "
        "(AD-731). Regression of BF-278."
    )
    assert "image_url" not in serialized, (
        "image_url shape is the post-resolution OpenAI shape; the bus must "
        "carry the attachment_ref source shape (AD-731)."
    )


@pytest.mark.asyncio
async def test_resolve_attachment_refs_rewrites_to_openai_image_url_shape(
    store_with_png: tuple[_InMemoryAttachmentStore, str],
) -> None:
    """Invariant #2 — resolver emits OpenAI image_url, never Anthropic shape."""
    store, sha = store_with_png

    client = OpenAICompatibleClient(attachment_store=store)  # type: ignore[arg-type]
    bus_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {
                    "type": "image",
                    "source": {
                        "type": "attachment_ref",
                        "sha256": sha,
                        "media_type": "image/png",
                    },
                },
            ],
        }
    ]

    resolved = await client._resolve_attachment_refs_for_openai(bus_messages)
    blocks = resolved[0]["content"]
    image_blocks = [b for b in blocks if b.get("type") == "image_url"]
    assert len(image_blocks) == 1

    url = image_blocks[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,"), url
    # Round-trip the bytes to confirm fidelity.
    decoded = base64.b64decode(url.split(",", 1)[1])
    assert decoded == _PNG_1X1

    # Forbidden shapes (BF-268 regression guard).
    assert not any(b.get("type") == "image" for b in blocks), (
        "BF-268: Anthropic-shape image blocks must be rewritten — leaving "
        "them in causes the Copilot proxy to silently drop the image."
    )
    serialized = json.dumps(resolved)
    assert "attachment_ref" not in serialized, (
        "resolver must NOT leave attachment_ref shapes downstream of the "
        "HTTP boundary (AD-731 resolver contract)."
    )
    assert "source" not in serialized or '"type": "image_url"' in serialized, (
        "Anthropic source.base64 shape must not survive past the resolver."
    )


@pytest.mark.asyncio
async def test_call_openai_posts_image_url_shape_to_wire(
    store_with_png: tuple[_InMemoryAttachmentStore, str],
) -> None:
    """Invariant #3 — end-to-end POST body carries OpenAI image_url.

    This is the layer ``tmp_capture_proxy.py`` exercised live during BF-278.
    The MockTransport here observes the same boundary in CI.
    """
    store, sha = store_with_png

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            },
        )

    transport = httpx.MockTransport(handler)
    mock_client = httpx.AsyncClient(transport=transport, base_url="http://test/v1/")
    try:
        oai_client = OpenAICompatibleClient(attachment_store=store)  # type: ignore[arg-type]
        request = LLMRequest(
            prompt="",
            system_prompt="you are vision",
            tier="vision",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {
                            "type": "image",
                            "source": {
                                "type": "attachment_ref",
                                "sha256": sha,
                                "media_type": "image/png",
                            },
                        },
                    ],
                }
            ],
        )

        await oai_client._call_openai(
            request, model="qwen3.6:27b", client=mock_client, timeout=5.0
        )
    finally:
        await mock_client.aclose()

    body = captured["body"]
    user_content = next(
        m["content"] for m in body["messages"] if m["role"] == "user"
    )
    types_on_wire = {b.get("type") for b in user_content}
    assert "image_url" in types_on_wire, (
        f"wire payload must contain image_url block; got types={types_on_wire}"
    )
    assert "image" not in types_on_wire, (
        "Anthropic source-shape image block leaked onto the wire — Copilot "
        "proxy / Ollama qwen3.6 silently reject it (BF-268, BF-278)."
    )
    image_block = next(b for b in user_content if b.get("type") == "image_url")
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")
    # System prompt must be present and string-shaped (BF-277).
    sys_msg = next(m for m in body["messages"] if m["role"] == "system")
    assert isinstance(sys_msg["content"], (str, list)), (
        "system message content shape regression (BF-277)."
    )
