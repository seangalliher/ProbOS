"""AD-746 Layer 2 — Per-agent ``bound_sources`` filtering contract tests.

Verifies default profile behavior, WM fan-out filtering, episodic-anchor
scoping, and fused-frame intersection semantics.
"""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from probos.crew_profile import CrewProfile, PerceptionProfile


def _make_jpeg(color: tuple[int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def _store(runtime: object, frame_bytes: bytes) -> str:
    from probos.routers.chat import _get_attachment_store

    store = _get_attachment_store(runtime)
    sha = hashlib.sha256(frame_bytes).hexdigest()
    await store.write(sha, frame_bytes, "image/jpeg")
    return sha


def test_default_bound_sources_is_both() -> None:
    """Default ``bound_sources`` = ['camera','screen'] (back-compat).
    Legacy profile JSON that omits the field reads the same."""
    p = PerceptionProfile()
    assert p.bound_sources == ["camera", "screen"]
    # from_dict on a legacy JSON without the key.
    legacy = PerceptionProfile.from_dict({})
    assert legacy.bound_sources == ["camera", "screen"]


def test_bound_sources_filter_restricts_wm_fan_out() -> None:
    """An agent bound to ``['camera']`` is dropped for a screen-only frame."""
    from unittest.mock import MagicMock
    from probos.perception.consumer import VisionConsumer
    from probos.config import SystemConfig

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.intent_bus = MagicMock()

    # Typed CrewProfile values (was MagicMock) so a production read of any
    # profile field other than ``perception`` surfaces instead of auto-faking.
    profile_store = MagicMock()
    counselor_profile = CrewProfile(agent_id="counselor", agent_type="counselor")
    counselor_profile.perception = PerceptionProfile(bound_sources=["camera"])
    ops_profile = CrewProfile(agent_id="ops", agent_type="operations")
    ops_profile.perception = PerceptionProfile(bound_sources=["screen"])
    legacy_profile = CrewProfile(agent_id="legacy", agent_type="counselor")
    legacy_profile.perception = PerceptionProfile()  # default both
    profile_store.get.side_effect = lambda aid: {
        "counselor": counselor_profile,
        "ops": ops_profile,
        "legacy": legacy_profile,
    }.get(aid)
    runtime.profile_store = profile_store

    consumer = VisionConsumer(runtime)
    # Screen-only frame.
    kept = consumer._filter_by_bound_sources(
        ["counselor", "ops", "legacy"], ["screen"],
    )
    assert "counselor" not in kept  # camera-bound; screen frame excluded
    assert "ops" in kept
    assert "legacy" in kept


def test_bound_sources_fused_visible_if_any_intersect() -> None:
    """Fused (camera+screen) tick: an agent bound to just camera should
    still see it (one source matches)."""
    from unittest.mock import MagicMock
    from probos.perception.consumer import VisionConsumer
    from probos.config import SystemConfig

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.intent_bus = MagicMock()
    profile_store = MagicMock()
    p = CrewProfile(agent_id="counselor", agent_type="counselor")
    p.perception = PerceptionProfile(bound_sources=["camera"])
    profile_store.get.return_value = p
    runtime.profile_store = profile_store
    consumer = VisionConsumer(runtime)
    kept = consumer._filter_by_bound_sources(["counselor"], ["camera", "screen"])
    assert kept == ["counselor"]


@pytest.mark.asyncio
async def test_bound_sources_restricts_episodic_anchor(tmp_path) -> None:
    """Camera-only frame anchors only agents whose binding includes camera."""
    from unittest.mock import AsyncMock, MagicMock

    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.config import SystemConfig
    from probos.perception.consumer import VisionConsumer, reset_working_memories_for_tests
    from probos.routers.chat import _ATTACHMENT_STORE_CACHE
    from probos.types import LLMResponse

    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.attachments.attachments_dir = str(attachments_dir)
    runtime.config = cfg
    runtime._attachment_store = FilesystemAttachmentStore(attachments_dir)
    runtime.intent_bus = MagicMock()
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)
    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content="camera scene", model="vision-fake")
    )

    profile_store = MagicMock()
    counselor = CrewProfile(agent_id="counselor", agent_type="counselor")
    counselor.perception = PerceptionProfile(bound_sources=["camera"])
    ops = CrewProfile(agent_id="ops", agent_type="operations")
    ops.perception = PerceptionProfile(bound_sources=["screen"])
    profile_store.get.side_effect = lambda aid: {
        "counselor": counselor,
        "ops": ops,
    }.get(aid)
    runtime.profile_store = profile_store

    _ATTACHMENT_STORE_CACHE.clear()
    reset_working_memories_for_tests()
    try:
        consumer = VisionConsumer(runtime)
        consumer.register_observer("counselor")
        consumer.register_observer("ops")
        sha = await _store(runtime, _make_jpeg((20, 20, 20)))
        from probos.types import IntentMessage

        await consumer._process(
            IntentMessage(
                intent="vision_observation",
                params={
                    "attachment_ref": sha,
                    "source": "camera",
                    "session_id": "ad746-anchor",
                },
            )
        )
        assert runtime.episodic_memory.store.await_count == 1
        episode = runtime.episodic_memory.store.await_args.args[0]
        assert set(episode.agent_ids) == {"counselor"}
    finally:
        reset_working_memories_for_tests()
        _ATTACHMENT_STORE_CACHE.clear()
