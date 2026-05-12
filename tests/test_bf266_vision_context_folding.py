"""BF-266: Regression test for vision DM context folding.

AD-730 (Wave 151) shipped vision pipe-through but the agent's LLM call
discarded the fully-assembled user_message (containing temporal awareness,
working memory, episodic recall, session history, avatar self-observation,
and the intent self-tag instruction) when vision_messages was present.
Result: the LLM received the image but lost all conversational context,
producing thin first-turn responses that asked meta-questions instead of
describing the image.

BF-266 (2026-05-11) introduced `_enrich_vision_messages_with_context()`
to fold the user_message into the multimodal content array, preserving
image blocks. These tests lock the contract.
"""
from __future__ import annotations

from probos.cognitive.cognitive_agent import _enrich_vision_messages_with_context


def _make_router_built_vision_messages(
    raw_text: str = "describe this image",
    *,
    image_count: int = 1,
) -> list[dict]:
    """Mirror what routers/agents.py builds via build_multimodal_messages.

    AD-731 (Wave 152): wire shape is ``attachment_ref`` (SHA-256 + media_type),
    not inline base64. The LLM client resolves refs just before HTTP POST.
    """
    content: list[dict] = [{"type": "text", "text": raw_text}]
    for i in range(image_count):
        content.append({
            "type": "image",
            "source": {
                "type": "attachment_ref",
                "sha256": f"sha-image-{i}",
                "media_type": "image/png",
            },
        })
    return [{"role": "user", "content": content}]


def test_enrich_replaces_raw_text_with_user_message():
    """The raw Captain text in vision_messages is replaced with the
    fully-assembled user_message (which already contains the Captain text
    embedded in conversational context)."""
    vision = _make_router_built_vision_messages(raw_text="raw")
    user_message = (
        "--- Temporal Awareness ---\n"
        "Time: 14:23 UTC. Uptime: 2h.\n"
        "---\n\n"
        "Working memory:\n"
        "  Captain DM to Counselor: 'raw' -> responded\n\n"
        "Captain says: raw"
    )

    out = _enrich_vision_messages_with_context(vision, user_message)
    assert out is not None
    assert len(out) == 1
    assert out[0]["role"] == "user"
    content = out[0]["content"]
    # First block is the assembled user_message text.
    assert content[0]["type"] == "text"
    assert content[0]["text"] == user_message
    # The raw "describe this image" alone is NOT what gets sent — the full
    # assembled user_message is. The Captain text remains accessible because
    # it's embedded inside the user_message.
    assert "Temporal Awareness" in content[0]["text"]
    assert "Working memory" in content[0]["text"]
    assert "Captain says: raw" in content[0]["text"]


def test_enrich_preserves_image_blocks():
    """All image blocks from the router output survive the enrichment
    pass — none are lost, none are duplicated."""
    vision = _make_router_built_vision_messages(image_count=2)
    out = _enrich_vision_messages_with_context(vision, "user message")
    assert out is not None
    content = out[0]["content"]
    image_blocks = [c for c in content if c.get("type") == "image"]
    assert len(image_blocks) == 2
    assert image_blocks[0]["source"]["sha256"] == "sha-image-0"
    assert image_blocks[1]["source"]["sha256"] == "sha-image-1"


def test_enrich_returns_none_when_no_image_blocks():
    """If router somehow produced vision_messages without image blocks
    (text-only attachments mistakenly routed here), return None so the
    caller can degrade to text-only path."""
    text_only = [{"role": "user", "content": [{"type": "text", "text": "raw"}]}]
    out = _enrich_vision_messages_with_context(text_only, "user message")
    assert out is None


def test_enrich_returns_none_for_empty_messages():
    """Empty input returns None — caller degrades."""
    assert _enrich_vision_messages_with_context([], "user message") is None


def test_enrich_returns_none_for_malformed_messages():
    """Malformed input (non-dict, missing content) returns None instead
    of raising. Tier-2 degrade pattern."""
    assert _enrich_vision_messages_with_context([{"role": "user"}], "msg") is None
    assert _enrich_vision_messages_with_context(
        [{"role": "user", "content": "not a list"}], "msg"
    ) is None


def test_enrich_does_not_mutate_input():
    """Pure function: original vision_messages unchanged after call."""
    vision = _make_router_built_vision_messages(raw_text="raw")
    original_content = list(vision[0]["content"])  # shallow copy of refs
    original_text_value = vision[0]["content"][0]["text"]

    _ = _enrich_vision_messages_with_context(vision, "ASSEMBLED_USER_MESSAGE")

    # Original raw text still in place.
    assert vision[0]["content"][0]["text"] == original_text_value
    # Original structure unchanged.
    assert vision[0]["content"] is not original_content  # we made a copy
    assert len(vision[0]["content"]) == 2


def test_enrich_image_blocks_appear_after_text():
    """Anthropic vision API convention: text content first, then images.
    The enriched output preserves this ordering."""
    vision = _make_router_built_vision_messages(image_count=1)
    out = _enrich_vision_messages_with_context(vision, "context goes here")
    assert out is not None
    content = out[0]["content"]
    # Block 0 is text.
    assert content[0]["type"] == "text"
    # All subsequent blocks are images.
    for block in content[1:]:
        assert block["type"] == "image"


def test_enrich_handles_realistic_user_message_size():
    """Realistic user_message can be 2000-5000 chars with all context
    folded in. Enrichment must handle this without truncation or error."""
    realistic_user_message = (
        "--- Temporal Awareness ---\n"
        + "Time, uptime, last action info.\n" * 20
        + "---\n\nWorking memory:\n"
        + "  Recent conversation summary.\n" * 30
        + "\nPrevious conversation:\n"
        + "  Captain: previous turn 1\n  Ezri: response 1\n" * 5
        + "\nCaptain says: tell me about this image"
    )
    assert len(realistic_user_message) > 1500  # confirm test setup is realistic

    vision = _make_router_built_vision_messages(raw_text="tell me about this image")
    out = _enrich_vision_messages_with_context(vision, realistic_user_message)
    assert out is not None
    assert out[0]["content"][0]["text"] == realistic_user_message
    assert any(c.get("type") == "image" for c in out[0]["content"])
