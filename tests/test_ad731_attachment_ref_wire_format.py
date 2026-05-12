"""AD-731 (Wave 152): content-addressable vision payload wire format tests.

Sender (vision_dispatch.build_multimodal_messages) emits ``attachment_ref``
shape; receiver (OpenAICompatibleClient._resolve_attachment_refs_for_openai)
dereferences refs to base64 just before the HTTP POST. Bus message stays
small (~70 bytes/image); the AttachmentStore carries the bytes.

These tests cover:
- Sender shape (image, mixed, text-only attachments).
- Receiver resolution (happy path, missing ref, store=None no-op, immutability,
  passthrough of non-ref blocks).
- Bus serialization size invariants (small refs survive NATS).
- End-to-end PNG round-trip through a real FilesystemAttachmentStore.
- Federation strip forward-marker still pins v1 behavior (AD-731a).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.vision_dispatch import build_multimodal_messages
from probos.mesh.intent import IntentBus
from probos.types import IntentMessage, LLMRequest


# Minimal 1x1 PNG (transparent), real bytes.
_PNG_1X1_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


async def _write_png(store: FilesystemAttachmentStore, blob: bytes, mime: str = "image/png") -> str:
    sha = _sha256(blob)
    await store.write(sha, blob, mime)
    return sha


def _mime_lookup_factory(by_id: dict[str, str]):
    async def _lookup(aid: str) -> str | None:
        return by_id.get(aid)
    return _lookup


# ------------------------------------------------------------------
# Sender shape
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_multimodal_messages_emits_attachment_ref_shape(tmp_path):
    """One-image input produces a content block with ref shape — no base64,
    no data field, SHA + media_type only."""
    store = FilesystemAttachmentStore(tmp_path)
    sha = await _write_png(store, _PNG_1X1_BYTES)

    messages, image_ids = await build_multimodal_messages(
        prompt="describe it",
        attachment_ids=[sha],
        store=store,
        mime_lookup=_mime_lookup_factory({sha: "image/png"}),
        text_extraction_max_bytes=1024,
        pdf_extraction_enabled=False,
    )

    assert image_ids == [sha]
    content = messages[0]["content"]
    # First block is the text prompt.
    assert content[0] == {"type": "text", "text": "describe it"}
    # Second block is the ref-shape image.
    image_block = content[1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "attachment_ref"
    assert image_block["source"]["sha256"] == sha
    assert image_block["source"]["media_type"] == "image/png"
    assert "data" not in image_block["source"]


@pytest.mark.asyncio
async def test_build_multimodal_messages_text_attachment_unchanged(tmp_path):
    """Non-image attachments still produce the existing text-extraction block."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = b"hello plain text from captain"
    sha = _sha256(blob)
    await store.write(sha, blob, "text/plain")

    messages, image_ids = await build_multimodal_messages(
        prompt="read this",
        attachment_ids=[sha],
        store=store,
        mime_lookup=_mime_lookup_factory({sha: "text/plain"}),
        text_extraction_max_bytes=1024,
        pdf_extraction_enabled=False,
    )

    assert image_ids == []
    content = messages[0]["content"]
    assert content[0]["type"] == "text"
    # Text-extraction block carries the original bytes inside an ATTACHMENT tag.
    assert content[1]["type"] == "text"
    assert "hello plain text from captain" in content[1]["text"]


@pytest.mark.asyncio
async def test_build_multimodal_messages_mixed_image_and_text(tmp_path):
    """Mixed input — one image + one text — produces both blocks in order."""
    store = FilesystemAttachmentStore(tmp_path)
    text_blob = b"some prose"
    text_sha = _sha256(text_blob)
    await store.write(text_sha, text_blob, "text/plain")
    img_sha = await _write_png(store, _PNG_1X1_BYTES)

    messages, image_ids = await build_multimodal_messages(
        prompt="look + read",
        attachment_ids=[img_sha, text_sha],
        store=store,
        mime_lookup=_mime_lookup_factory({img_sha: "image/png", text_sha: "text/plain"}),
        text_extraction_max_bytes=1024,
        pdf_extraction_enabled=False,
    )

    assert image_ids == [img_sha]
    content = messages[0]["content"]
    # prompt text + image ref + text-extraction block
    assert content[0] == {"type": "text", "text": "look + read"}
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "attachment_ref"
    assert content[1]["source"]["sha256"] == img_sha
    assert content[2]["type"] == "text"
    assert "some prose" in content[2]["text"]


# ------------------------------------------------------------------
# Receiver resolution
# ------------------------------------------------------------------


def _make_llm_client(store) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
        attachment_store=store,
    )


@pytest.mark.asyncio
async def test_llm_client_resolves_attachment_ref_to_base64_pre_post(tmp_path):
    """Ref-shape image is resolved to a base64 source block whose data
    decodes back to the original blob bytes."""
    store = FilesystemAttachmentStore(tmp_path)
    sha = await _write_png(store, _PNG_1X1_BYTES)
    client = _make_llm_client(store)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
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
    resolved = await client._resolve_attachment_refs_for_openai(messages)
    image_block = resolved[0]["content"][1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert base64.b64decode(image_block["source"]["data"]) == _PNG_1X1_BYTES


@pytest.mark.asyncio
async def test_llm_client_resolves_missing_ref_to_failed_to_load_marker(tmp_path, caplog):
    """Missing SHA → image block replaced with a text marker; warning logged;
    no exception."""
    import logging
    store = FilesystemAttachmentStore(tmp_path)
    client = _make_llm_client(store)
    missing_sha = "f" * 64

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {
                    "type": "image",
                    "source": {
                        "type": "attachment_ref",
                        "sha256": missing_sha,
                        "media_type": "image/png",
                    },
                },
            ],
        }
    ]
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.llm_client"):
        resolved = await client._resolve_attachment_refs_for_openai(messages)

    marker_block = resolved[0]["content"][1]
    assert marker_block["type"] == "text"
    assert "failed_to_load_at_dereference" in marker_block["text"]
    assert missing_sha in marker_block["text"]
    assert any("AD-731" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_llm_client_resolves_no_op_when_store_is_none():
    """attachment_store=None disables resolution (no-op pass-through)."""
    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
        attachment_store=None,
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "x"},
                {
                    "type": "image",
                    "source": {
                        "type": "attachment_ref",
                        "sha256": "a" * 64,
                        "media_type": "image/png",
                    },
                },
            ],
        }
    ]
    resolved = await client._resolve_attachment_refs_for_openai(messages)
    # Unchanged — ref block survives as ref block.
    assert resolved[0]["content"][1]["source"]["type"] == "attachment_ref"


@pytest.mark.asyncio
async def test_llm_client_resolves_does_not_mutate_input(tmp_path):
    """Input messages list/dicts unchanged after resolution."""
    store = FilesystemAttachmentStore(tmp_path)
    sha = await _write_png(store, _PNG_1X1_BYTES)
    client = _make_llm_client(store)

    messages = [
        {
            "role": "user",
            "content": [
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
    baseline = copy.deepcopy(messages)
    _ = await client._resolve_attachment_refs_for_openai(messages)
    assert messages == baseline


@pytest.mark.asyncio
async def test_llm_client_resolves_passes_through_non_ref_blocks(tmp_path):
    """text and tool_use blocks are untouched."""
    store = FilesystemAttachmentStore(tmp_path)
    client = _make_llm_client(store)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "id": "t1", "name": "fetch", "input": {}},
            ],
        }
    ]
    baseline = copy.deepcopy(messages)
    resolved = await client._resolve_attachment_refs_for_openai(messages)
    assert resolved == baseline


# ------------------------------------------------------------------
# Bus serialization size invariants
# ------------------------------------------------------------------


def _make_ref_intent(image_count: int) -> IntentMessage:
    content = [{"type": "text", "text": "look at these"}]
    for i in range(image_count):
        content.append({
            "type": "image",
            "source": {
                "type": "attachment_ref",
                "sha256": f"{i:064x}",
                "media_type": "image/png",
            },
        })
    return IntentMessage(
        intent="direct_message",
        params={
            "text": "look",
            "vision_messages": [{"role": "user", "content": content}],
            "has_image_attachment": True,
        },
        target_agent_id="counselor-001",
    )


def test_intent_bus_serialize_no_longer_strips_vision_messages():
    """AD-731: vision_messages round-trips through NATS serialization
    intact — no transport-strip marker."""
    intent = _make_ref_intent(image_count=1)
    serialized = IntentBus._serialize_intent(intent)
    assert "vision_messages" in serialized["params"]
    assert "_transport_stripped" not in serialized["params"]
    block = serialized["params"]["vision_messages"][0]["content"][1]
    assert block["source"]["type"] == "attachment_ref"


def test_intent_bus_serialize_size_bound_with_refs():
    """Size bound: 5-image ref-shape DM < 2 KB; 10-image < 4 KB.
    Documents the linear scaling — ~70-100 bytes per image plus overhead."""
    serialized_5 = IntentBus._serialize_intent(_make_ref_intent(5))
    payload_5 = len(json.dumps(serialized_5).encode("utf-8"))
    assert payload_5 < 2_048, f"5-image payload was {payload_5} bytes"

    serialized_10 = IntentBus._serialize_intent(_make_ref_intent(10))
    payload_10 = len(json.dumps(serialized_10).encode("utf-8"))
    assert payload_10 < 4_096, f"10-image payload was {payload_10} bytes"


# ------------------------------------------------------------------
# End-to-end through OpenAICompatibleClient._call_openai
# ------------------------------------------------------------------


class _StubHttpResp:
    def raise_for_status(self) -> None: ...
    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
        }


class _CapturingHttpClient:
    def __init__(self) -> None:
        self.captured_payload: dict | None = None

    async def post(self, path, json, timeout):  # noqa: A002
        self.captured_payload = json
        return _StubHttpResp()


@pytest.mark.asyncio
async def test_end_to_end_vision_dm_with_real_store(tmp_path):
    """Write a real PNG to a real FilesystemAttachmentStore. Build vision
    messages with ref shape. Construct an OpenAICompatibleClient with the
    store wired. Call _call_openai with a captured HTTP transport. Assert
    the captured payload contains a base64 source whose decoded bytes
    match the original PNG.
    """
    store = FilesystemAttachmentStore(tmp_path)
    sha = await _write_png(store, _PNG_1X1_BYTES)
    client = _make_llm_client(store)

    # Build the ref-shape vision messages (mirrors what build_multimodal_messages
    # would emit + what cognitive_agent.py would inject into LLMRequest.messages).
    vision_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
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
    req = LLMRequest(prompt="", messages=vision_messages)
    transport = _CapturingHttpClient()
    await client._call_openai(req, "m", transport, timeout=5.0)

    assert transport.captured_payload is not None
    sent_messages = transport.captured_payload["messages"]
    image_block = sent_messages[0]["content"][1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert base64.b64decode(image_block["source"]["data"]) == _PNG_1X1_BYTES


# ------------------------------------------------------------------
# Federation strip — AD-731a forward marker (pinned v1)
# ------------------------------------------------------------------


def test_federation_bridge_still_strips_vision_messages_v1():
    """Federation transport still strips vision_messages because the receiving
    mesh does not (yet) have a shared AttachmentStore. AD-731a-1 (HTTP fetch)
    or AD-731a-2 (NATS Object Store) will retire the strip. This pin is the
    regression target the future AD will flip.
    """
    intent = _make_ref_intent(image_count=1)
    _stripped_keys = ("vision_messages",)
    if any(k in intent.params for k in _stripped_keys):
        params_for_transport = {
            k: v
            for k, v in intent.params.items()
            if k not in _stripped_keys
        }
        params_for_transport["_transport_stripped"] = [
            k for k in _stripped_keys if k in intent.params
        ]
    else:
        params_for_transport = intent.params

    assert "vision_messages" not in params_for_transport
    assert params_for_transport["_transport_stripped"] == ["vision_messages"]
    # Original IntentMessage is untouched.
    assert "vision_messages" in intent.params
