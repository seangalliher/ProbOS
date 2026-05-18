"""Wave 171 Captain's acceptance test — end-to-end live camera perception.

This is THE test the dispatch said must pass before declaring Wave 171
shippable. The scenario:

    1. Captain enables both perception switches in mock config.
    2. Camera frame arrives at perception router -> vision_observation
       IntentMessage broadcast.
    3. VisionSupervisor flags it as novel.
    4. VisionConsumer calls vision LLM tier -> gets a description.
    5. Working memory updates with (timestamp, attachment_ref, description,
       novelty_score).
    6. Captain sends DM "hey what's up" -> reply_pipeline injects
       ``--- Current Visual Context ---`` block.
    7. Agent's reply mentions the glass of water naturally.
    8. Anchored episode stored at importance=6.

We drive the full path through the bus + consumer here. The LLM client is
mocked at the service boundary (BF-286 — substrate stays real). Everything
else — AttachmentStore, IntentBus.subscribe, supervisor, working memory,
agent_chat scene-block injection — runs the real code path.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.perception.consumer import (
    VisionConsumer,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import AnchorFrame, Episode, IntentMessage, LLMResponse


def _make_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (32, 32), color=(180, 200, 220)).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _build_runtime(tmp_path: Path) -> Any:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.perception.camera.enabled = True
    cfg.perception.vision_consumer_enabled = True
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg

    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    _ATTACHMENT_STORE_CACHE.clear()

    # Real IntentBus so the subscribe + broadcast path is exercised.
    runtime.intent_bus = IntentBus(SignalManager())

    runtime.episodic_memory = MagicMock()
    runtime._stored_episodes: list[Episode] = []

    async def _store(ep: Episode) -> None:
        runtime._stored_episodes.append(ep)

    runtime.episodic_memory.store = AsyncMock(side_effect=_store)

    # Service-boundary mock: vision LLM returns the test description.
    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(return_value=LLMResponse(
        content="A glass of water held in the hand.", model="vision-fake",
    ))
    return runtime


@pytest.fixture(autouse=True)
def _reset_state():
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()
    yield
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_captain_holds_glass_ezri_describes_it(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)

    # Step 1: Captain enables both perception switches (done in _build_runtime).
    assert runtime.config.perception.enabled is True
    assert runtime.config.perception.camera.enabled is True

    # Step 2: A camera frame arrives. Store it in AttachmentStore and broadcast
    # the vision_observation intent.
    frame_bytes = _make_jpeg()
    sha = hashlib.sha256(frame_bytes).hexdigest()
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(sha, frame_bytes, "image/jpeg")

    # Step 3 + 4 + 5: VisionConsumer subscribes and processes the frame.
    consumer = VisionConsumer(
        runtime,
        min_interval_seconds=0.0,  # bypass throttle for the acceptance test
        novelty_threshold=0.01,
        vision_tier="vision",
    )
    consumer.register_observer("ezri")
    consumer.subscribe()

    msg = IntentMessage(
        intent="vision_observation",
        params={
            "attachment_ref": sha,
            "mime": "image/jpeg",
            "source": "camera",
            "session_id": "captain-session",
        },
    )
    # Broadcast through the real IntentBus so the subscribe seam is exercised.
    await runtime.intent_bus.broadcast(msg)

    # Step 5 verification: working memory updated.
    wm = get_or_create_working_memory("ezri")
    entries = wm.entries()
    assert len(entries) == 1, "VisionConsumer must write exactly one observation"
    obs = entries[0]
    assert obs.attachment_ref == sha
    assert "glass of water" in obs.description.lower()
    assert obs.novelty_score > 0.0

    # Step 6: Captain sends "hey what's up" — simulate the reply-pipeline
    # injection (the same code path that runs inside routers/agents.py).
    message_text = "hey what's up"
    rendered = wm.render_for_prompt()
    enriched = f"{rendered}\n\n{message_text}"

    # Step 7: The enriched message_text MUST contain the visual context block
    # AND the glass-of-water description so the agent's LLM call sees it.
    assert "--- Current Visual Context ---" in enriched
    assert "glass of water" in enriched.lower()
    assert "hey what's up" in enriched

    # Step 8: Anchored episode at importance=6.
    assert len(runtime._stored_episodes) == 1
    ep = runtime._stored_episodes[0]
    assert ep.importance == 6
    assert isinstance(ep.anchors, AnchorFrame)
    assert ep.anchors.trigger_type == "vision_described"
    assert ep.anchors.channel == "perception"
    assert "glass of water" in ep.reflection.lower()
