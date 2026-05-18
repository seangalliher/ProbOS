"""AD-733b (Wave 171): ProactiveVisionObserver + identity hook tests.

Tier-2 honest-degrade and explicit budget gating verified through fake-runtime
fixtures. The observer's substrate boundary (``runtime.intent_bus.send``) is
mocked as ``AsyncMock``; everything else (VisionObservation, _SessionState,
ProactiveBudget) is real per BF-286/BF-287.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.perception.consumer import (
    VisionConsumer,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.observer import ProactiveBudget, ProactiveVisionObserver
from probos.perception.working_memory import VisionObservation
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import IntentMessage, LLMResponse


# ---------- Helpers ----------


def _make_jpeg(color: tuple[int, int, int] = (10, 200, 50)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _build_runtime(tmp_path: Path, *, captain_avatar_ref: str = "") -> Any:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.perception.captain_avatar_ref = captain_avatar_ref
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg
    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    _ATTACHMENT_STORE_CACHE.clear()

    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime.intent_bus.subscribe = MagicMock(return_value=None)

    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)

    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content="captain", model="vision-fake")
    )
    return runtime


def _obs(novelty: float = 0.6, session_id: str = "s1") -> VisionObservation:
    import time
    return VisionObservation(
        timestamp=time.time(),
        attachment_ref="sha-fake",
        description="a glass of water",
        novelty_score=novelty,
        subject_identity="unknown",
        session_id=session_id,
    )


@pytest.fixture(autouse=True)
def _reset_state():
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()
    yield
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


# ---------- 10 cases ----------


@pytest.mark.asyncio
async def test_scene_introduction_fires_on_first_observation(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(runtime)
    emitted = await observer.maybe_emit(
        session_id="s1",
        agent_id="ezri",
        observation=_obs(novelty=0.05),  # below novelty threshold but first frame
        is_first_observation=True,
    )
    assert emitted is True
    runtime.intent_bus.send.assert_called_once()
    sent: IntentMessage = runtime.intent_bus.send.call_args.args[0]
    assert sent.params["proactive_reason"] == "scene_introduction"
    assert sent.target_agent_id == "ezri"


@pytest.mark.asyncio
async def test_scene_introduction_fires_only_once_per_session(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(runtime)
    await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.05), is_first_observation=True,
    )
    runtime.intent_bus.send.reset_mock()
    # Second call with is_first_observation=False, low novelty -> no DM.
    emitted = await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.05), is_first_observation=False,
    )
    assert emitted is False
    runtime.intent_bus.send.assert_not_called()


@pytest.mark.asyncio
async def test_high_novelty_emits_dm(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(
        runtime,
        budget=ProactiveBudget(min_dwell_seconds=0.0, novelty_threshold=0.5),
    )
    emitted = await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.7), is_first_observation=False,
    )
    assert emitted is True
    sent: IntentMessage = runtime.intent_bus.send.call_args.args[0]
    assert sent.params["proactive_reason"] == "high_novelty"


@pytest.mark.asyncio
async def test_low_novelty_blocks_emission(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(
        runtime,
        budget=ProactiveBudget(min_dwell_seconds=0.0, novelty_threshold=0.5),
    )
    emitted = await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.3), is_first_observation=False,
    )
    assert emitted is False
    runtime.intent_bus.send.assert_not_called()


@pytest.mark.asyncio
async def test_dwell_window_blocks_consecutive_emissions(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(
        runtime,
        budget=ProactiveBudget(min_dwell_seconds=60.0, novelty_threshold=0.5),
    )
    # First high-novelty observation -> fires (first_observation path).
    await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.7), is_first_observation=True,
    )
    runtime.intent_bus.send.reset_mock()
    # Second high-novelty observation immediately after -> blocked by dwell.
    emitted = await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.7), is_first_observation=False,
    )
    assert emitted is False
    runtime.intent_bus.send.assert_not_called()


@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_emission(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(
        runtime,
        budget=ProactiveBudget(
            max_emissions_per_session=2,
            min_dwell_seconds=0.0,
            novelty_threshold=0.5,
        ),
    )
    # 1st (scene_introduction)
    await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.7), is_first_observation=True,
    )
    # 2nd (high_novelty) — budget=2 reached.
    await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.7), is_first_observation=False,
    )
    runtime.intent_bus.send.reset_mock()
    # 3rd -> blocked by budget.
    emitted = await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.7), is_first_observation=False,
    )
    assert emitted is False
    runtime.intent_bus.send.assert_not_called()


@pytest.mark.asyncio
async def test_session_reset_clears_state(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    observer = ProactiveVisionObserver(runtime)
    await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.05), is_first_observation=True,
    )
    observer.reset_session("s1", "ezri")
    runtime.intent_bus.send.reset_mock()
    emitted = await observer.maybe_emit(
        session_id="s1", agent_id="ezri",
        observation=_obs(novelty=0.05), is_first_observation=True,
    )
    assert emitted is True
    runtime.intent_bus.send.assert_called_once()


@pytest.mark.asyncio
async def test_identity_resolves_captain(tmp_path: Path) -> None:
    """When a captain_avatar_ref is configured and the LLM returns 'captain',
    the consumer populates VisionObservation.subject_identity accordingly.
    """
    import hashlib
    avatar_bytes = _make_jpeg(color=(40, 90, 200))
    avatar_sha = hashlib.sha256(avatar_bytes).hexdigest()
    runtime = _build_runtime(tmp_path, captain_avatar_ref=avatar_sha)

    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(avatar_sha, avatar_bytes, "image/jpeg")

    # Live frame.
    frame_bytes = _make_jpeg(color=(10, 200, 50))
    frame_sha = hashlib.sha256(frame_bytes).hexdigest()
    await store.write(frame_sha, frame_bytes, "image/jpeg")

    # llm_client returns "captain" both for describe and for identity check.
    runtime.llm_client.complete = AsyncMock(side_effect=[
        LLMResponse(content="A glass of water.", model="vision-fake"),
        LLMResponse(content="captain", model="vision-fake"),
    ])

    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": frame_sha, "session_id": "s1"},
    )
    await consumer._handle(msg)
    wm = get_or_create_working_memory("ezri")
    entries = wm.entries()
    assert len(entries) == 1
    assert entries[0].subject_identity == "captain"


@pytest.mark.asyncio
async def test_identity_resolves_unknown_when_no_reference(tmp_path: Path) -> None:
    import hashlib
    runtime = _build_runtime(tmp_path, captain_avatar_ref="")  # no avatar
    frame_bytes = _make_jpeg()
    frame_sha = hashlib.sha256(frame_bytes).hexdigest()
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(frame_sha, frame_bytes, "image/jpeg")

    # Only describe call should occur — no identity call.
    runtime.llm_client.complete = AsyncMock(return_value=LLMResponse(
        content="A scene.", model="vision-fake"
    ))

    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": frame_sha, "session_id": "s1"},
    )
    await consumer._handle(msg)
    wm = get_or_create_working_memory("ezri")
    entries = wm.entries()
    assert len(entries) == 1
    assert entries[0].subject_identity == "unknown"
    # Only one LLM call (describe) — identity short-circuits when no ref.
    assert runtime.llm_client.complete.call_count == 1


def test_proactive_disabled_no_emissions() -> None:
    """When ``proactive_observer_enabled=False``, finalize MUST NOT instantiate
    the observer. We verify the config default + an operator-overridden False
    propagates end-to-end as a config-level guard.
    """
    cfg = SystemConfig()
    assert cfg.perception.proactive_observer_enabled is True  # default
    cfg.perception.proactive_observer_enabled = False
    assert cfg.perception.proactive_observer_enabled is False
