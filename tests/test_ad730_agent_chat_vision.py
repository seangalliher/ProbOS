"""AD-730 (Wave 151): vision pipe-through for per-agent DMs.

Covers:
  - image attachments route the agent's DM perception turn via the vision tier
  - vision_messages threaded through IntentMessage.params['vision_messages']
  - degraded vision tier => AD-732 honest-degrade (no intent dispatch)
  - text-only DM path unchanged when no images present
  - text/.txt attachments do not trigger the vision branch
  - episodic outcomes carry the has_image_attachment flag
  - LLMRequest preserves system_prompt alongside multimodal messages
  - vision tier wins over per-call tier when vision_messages is present
  - cfg.attachments.enabled=False short-circuits silently
  - multi-image DMs (all images included; documented for AD-730-2)
  - augmentation exception falls back to original message_text
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import CognitiveConfig
from probos.routers.agents import agent_chat


# Patch is_crew_agent to always return True for these tests.
_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


def _make_runtime(
    *,
    response_text: str = "I see the image.",
    vision_status: str = "operational",
    attachments_enabled: bool = True,
    captured_episodes: list | None = None,
):
    """Build a mock runtime sized for agent_chat() vision-branch tests."""
    runtime = MagicMock()

    # Registry
    agent = MagicMock()
    agent.id = "test-id"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent

    # Callsign
    runtime.callsign_registry.get_callsign.return_value = "Lynx"

    # Intent bus — capture the IntentMessage that was sent.
    intent_result = MagicMock()
    intent_result.result = response_text
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)

    # No recreation service / ward room — DM-only tests.
    runtime.recreation_service = None
    runtime.ward_room = None

    # Attachments config + AD-732 cognitive config (vision tier).
    # vision_tier="standard" → is_vision_tier_configured returns True
    # (legacy tier; always configured). vision_tier="vision" with no
    # llm_model_vision is_vision_tier_configured returns False (unconfigured).
    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(
            enabled=attachments_enabled,
            text_extraction_max_bytes=1024,
            pdf_extraction_enabled=False,
            vision_tier="standard",
        ),
        cognitive=CognitiveConfig(),
    )

    # LLM client health
    runtime.llm_client = MagicMock()
    runtime.llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {"standard": {"status": vision_status}},
            "overall": vision_status,
        },
    )

    # Episodic memory — capture stored episode (or disabled).
    if captured_episodes is not None:
        runtime.episodic_memory = MagicMock()

        async def _store(ep):
            captured_episodes.append(ep)

        runtime.episodic_memory.store = AsyncMock(side_effect=_store)
    else:
        runtime.episodic_memory = None

    # DM sanity gate
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    runtime.dm_sanity_gate = DmSanityGate()

    return runtime


def _req(message: str = "look at this", attachment_ids: list[str] | None = None):
    """Build a minimal AgentChatRequest stub."""
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = attachment_ids or []
    return r


def _fake_multimodal_messages(prompt: str, image_ids: list[str]):
    """Build a representative multimodal messages array shape.

    AD-731 (Wave 152): the wire shape is now an ``attachment_ref`` source
    block with a SHA-256 reference, NOT inline base64. The LLM client
    dereferences the ref to a base64 source block just before HTTP POST.
    """
    content: list[dict] = [{"type": "text", "text": prompt}]
    for aid in image_ids:
        content.append({
            "type": "image",
            "source": {
                "type": "attachment_ref",
                "sha256": aid,
                "media_type": "image/png",
            },
        })
    return [{"role": "user", "content": content}]


@pytest.mark.asyncio
async def test_dm_image_routes_to_vision_tier():
    """Image DM dispatches an intent carrying vision_messages with image content."""
    runtime = _make_runtime()
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert sent_intent.intent == "direct_message"
    assert sent_intent.params.get("vision_messages") is not None
    content = sent_intent.params["vision_messages"][0]["content"]
    assert any(item.get("type") == "image" for item in content)


@pytest.mark.asyncio
async def test_dm_image_passes_vision_messages_through_intent_params():
    """vision_messages and has_image_attachment land on IntentMessage.params."""
    runtime = _make_runtime()
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert "vision_messages" in sent_intent.params
    assert sent_intent.params.get("has_image_attachment") is True


@pytest.mark.asyncio
async def test_dm_image_with_degraded_vision_tier_returns_unhealthy_message():
    """AD-732: a configured-but-unhealthy vision tier returns the
    VISION_UNHEALTHY_MESSAGE honest-degrade text and does NOT dispatch the
    intent. vision_tier="standard" is "configured" for legacy reasons, so
    the unhealthy branch fires."""
    from probos.cognitive.vision_dispatch import VISION_UNHEALTHY_MESSAGE

    runtime = _make_runtime(vision_status="degraded")
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    aug = AsyncMock(return_value="look at this\n[Captain attached an image (id=sha-img-1)]")

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", aug), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        result = await agent_chat("test-id", req, runtime)

    # Honest-degrade: early return, no intent dispatch, no text-augmentation.
    runtime.intent_bus.send.assert_not_called()
    aug.assert_not_awaited()
    assert result["response"] == VISION_UNHEALTHY_MESSAGE
    assert result["callsign"] == "Lynx"
    assert result["agentId"] == "test-id"


@pytest.mark.asyncio
async def test_dm_no_attachments_unchanged_path():
    """Text-only DM has no vision branch artifacts on IntentMessage.params."""
    runtime = _make_runtime()
    req = _req(attachment_ids=[])

    with _CREW_PATCH:
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert "vision_messages" not in sent_intent.params
    assert "has_image_attachment" not in sent_intent.params
    assert sent_intent.params["text"] == "look at this"


@pytest.mark.asyncio
async def test_dm_text_only_attachment_no_vision_branch():
    """A .txt attachment has no image_ids so vision branch is skipped."""
    runtime = _make_runtime()
    req = _req(attachment_ids=["sha-txt-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        # No image — image_ids list is empty.
        return _fake_multimodal_messages(prompt, []), [], []

    aug = AsyncMock(return_value="look at this\n<ATTACHMENT id=sha-txt-1>hello</ATTACHMENT>")

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", aug), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert "vision_messages" not in sent_intent.params
    aug.assert_awaited_once()
    assert "<ATTACHMENT" in sent_intent.params["text"]


@pytest.mark.asyncio
async def test_dm_image_episode_has_image_attachment_flag():
    """Image DM stores episode with outcomes[0]['has_image_attachment'] = True."""
    captured: list = []
    runtime = _make_runtime(captured_episodes=captured)
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    assert captured, "expected episode to be stored"
    ep = captured[0]
    assert ep.outcomes[0]["has_image_attachment"] is True


@pytest.mark.asyncio
async def test_dm_no_attachments_episode_has_image_attachment_false():
    """Text-only DM stores episode with has_image_attachment = False default."""
    captured: list = []
    runtime = _make_runtime(captured_episodes=captured)
    req = _req(attachment_ids=[])

    with _CREW_PATCH:
        await agent_chat("test-id", req, runtime)

    assert captured, "expected episode to be stored"
    assert captured[0].outcomes[0]["has_image_attachment"] is False


@pytest.mark.asyncio
async def test_dm_vision_messages_preserves_system_prompt():
    """Image DM => the IntentMessage carries vision_messages AND original text.

    The original Captain text is preserved in params['text'] so episodic
    memory remains search-friendly while the LLM gets multimodal input.
    """
    runtime = _make_runtime()
    req = _req(message="describe this image", attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    # Original Captain text preserved (LLM gets full multimodal via vision_messages).
    assert sent_intent.params["text"] == "describe this image"
    msgs = sent_intent.params["vision_messages"]
    assert msgs[0]["role"] == "user"
    text_blocks = [c for c in msgs[0]["content"] if c.get("type") == "text"]
    assert any("describe this image" in b.get("text", "") for b in text_blocks)


@pytest.mark.asyncio
async def test_dm_vision_messages_set_alongside_text_when_image_present():
    """vision_messages and text are both populated; intent is direct_message."""
    runtime = _make_runtime()
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert sent_intent.intent == "direct_message"
    assert isinstance(sent_intent.params["text"], str)
    assert sent_intent.params["vision_messages"] is not None


@pytest.mark.asyncio
async def test_dm_image_with_attachments_disabled_falls_back_silently():
    """cfg.attachments.enabled=False => augmentation skipped, original text used."""
    runtime = _make_runtime(attachments_enabled=False)
    req = _req(attachment_ids=["sha-img-1"])

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages") as bmm, \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text") as aug:
        await agent_chat("test-id", req, runtime)
        bmm.assert_not_called()
        aug.assert_not_called()

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert "vision_messages" not in sent_intent.params
    assert sent_intent.params["text"] == "look at this"


@pytest.mark.asyncio
async def test_dm_multi_image_all_included_in_vision_messages():
    """Multi-image DM v1: all images included in vision_messages.

    Documents observed build_multimodal_messages behavior — every image
    attachment is added to the content array (no first-image-only cap).
    The AD-730-2 forward marker tracks any future per-image policy.
    """
    runtime = _make_runtime()
    req = _req(attachment_ids=["sha-img-1", "sha-img-2"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    msgs = sent_intent.params["vision_messages"]
    image_items = [c for c in msgs[0]["content"] if c.get("type") == "image"]
    assert len(image_items) == 2


@pytest.mark.asyncio
async def test_dm_augmentation_exception_falls_back_to_original_message():
    """build_multimodal_messages raising => original message_text preserved."""
    runtime = _make_runtime()
    req = _req(attachment_ids=["sha-img-1"])

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated")

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_boom), \
         patch("probos.cognitive.vision_dispatch.augment_prompt_with_attachment_text", AsyncMock()), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert "vision_messages" not in sent_intent.params
    assert sent_intent.params["text"] == "look at this"
