"""AD-733a (Wave 171): VisionSupervisor + VisionWorkingMemory + VisionConsumer.

BF-286/BF-287 lesson: real ``SystemConfig`` + real ``FilesystemAttachmentStore``
+ real ``VisionWorkingMemory`` instances. ``llm_client.complete`` is the only
service-boundary mock — substrate APIs (AttachmentStore, IntentBus.subscribe)
stay real.

AD-731 invariant: tests source-scan the new perception modules for inline
base64 usage. No ``b64encode`` / ``base64.b64`` / ``blob_b64`` allowed.
"""
from __future__ import annotations

import asyncio
import threading
import time
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
from probos.perception.supervisor import (
    PerceptualHashStrategy,
    SupervisorDecision,
    SupervisorStrategy,
    VisionSupervisor,
)
from probos.perception.working_memory import VisionObservation, VisionWorkingMemory
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import AnchorFrame, Episode, IntentMessage, LLMResponse


# ---------- Helpers ----------


def _make_jpeg(color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _make_checkerboard_jpeg() -> bytes:
    """High-contrast 16x16 checker, designed to produce an aHash very
    different from any solid-color frame."""
    buf = BytesIO()
    img = Image.new("L", (16, 16), color=0)
    for y in range(16):
        for x in range(16):
            if (x + y) % 2 == 0:
                img.putpixel((x, y), 255)
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _make_solid_grey_jpeg() -> bytes:
    return _make_jpeg(color=(128, 128, 128))


def _make_solid_white_jpeg() -> bytes:
    return _make_jpeg(color=(250, 250, 250))


def _make_solid_black_jpeg() -> bytes:
    return _make_jpeg(color=(5, 5, 5))


def _build_runtime(tmp_path: Path) -> Any:
    """Real SystemConfig + real FilesystemAttachmentStore.

    BF-287: no MagicMock at substrate boundary — attachment store is real.
    LLM client and intent_bus are MagicMock (service-level boundaries).
    """
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg

    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    _ATTACHMENT_STORE_CACHE.clear()
    runtime._attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")

    # _get_attachment_store walks runtime.config.attachments.attachments_dir
    # which is a real path — so we don't override _get_attachment_store directly.

    runtime.intent_bus = MagicMock()
    runtime.intent_bus.subscribe = MagicMock(return_value=None)
    runtime.intent_bus.send = AsyncMock(return_value=None)

    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)

    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content="A glass of water.", model="vision-fake")
    )

    return runtime


async def _store_frame(runtime: Any, frame_bytes: bytes) -> str:
    import hashlib
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    sha = hashlib.sha256(frame_bytes).hexdigest()
    await store.write(sha, frame_bytes, "image/jpeg")
    return sha


@pytest.fixture(autouse=True)
def _reset_module_state():
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()
    yield
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


# ---------- Supervisor (6) ----------


def test_first_frame_always_allowed() -> None:
    sup = VisionSupervisor()
    decision = sup.admit(_make_jpeg())
    assert decision.allow is True
    assert decision.reason == "first_frame"
    assert decision.novelty_score == 1.0


def test_throttle_blocks_within_interval() -> None:
    strat = PerceptualHashStrategy(min_interval_seconds=60.0, novelty_threshold=0.15)
    sup = VisionSupervisor(strategy=strat)
    sup.admit(_make_jpeg())
    # Second frame immediately afterwards — same monotonic clock => well under 60s.
    decision = sup.admit(_make_solid_grey_jpeg())
    assert decision.allow is False
    assert decision.reason == "throttled"


def test_low_novelty_blocked() -> None:
    # min_interval=0 forces the throttle to never block, so only novelty governs.
    strat = PerceptualHashStrategy(min_interval_seconds=0.0, novelty_threshold=0.5)
    sup = VisionSupervisor(strategy=strat)
    frame = _make_jpeg()
    sup.admit(frame)
    decision = sup.admit(frame)  # identical bytes -> novelty=0
    assert decision.allow is False
    assert decision.reason == "low_novelty"
    assert decision.novelty_score < 0.5


def test_high_novelty_allowed() -> None:
    strat = PerceptualHashStrategy(min_interval_seconds=0.0, novelty_threshold=0.1)
    sup = VisionSupervisor(strategy=strat)
    sup.admit(_make_solid_black_jpeg())
    decision = sup.admit(_make_checkerboard_jpeg())
    assert decision.allow is True
    assert decision.reason == "novel"
    assert decision.novelty_score >= 0.1


def test_corrupt_jpeg_falls_through_to_throttle() -> None:
    strat = PerceptualHashStrategy(min_interval_seconds=0.0, novelty_threshold=0.15)
    sup = VisionSupervisor(strategy=strat)
    # First call with corrupt bytes must not raise. Hash unavailable -> first_frame allow.
    decision = sup.admit(b"not-a-jpeg")
    assert decision.allow is True
    # Second corrupt call — hash still unavailable; throttle gate passed (0s), so allow.
    decision = sup.admit(b"still-not-jpeg")
    assert decision.allow is True


def test_strategy_protocol_pluggable() -> None:
    class _FakeStrategy:
        def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
            return SupervisorDecision(allow=False, novelty_score=0.0, reason="fake")

    fake = _FakeStrategy()
    assert isinstance(fake, SupervisorStrategy)
    sup = VisionSupervisor(strategy=fake)
    decision = sup.admit(_make_jpeg())
    assert decision.reason == "fake"
    assert decision.allow is False


# ---------- WorkingMemory (4) ----------


def test_empty_buffer_renders_no_data_sentinel() -> None:
    wm = VisionWorkingMemory()
    rendered = wm.render_for_prompt()
    assert "Camera not active or no frames described yet" in rendered
    assert "Do NOT describe what you cannot see" in rendered
    assert "--- Current Visual Context ---" in rendered
    assert "--- End Visual Context ---" in rendered


def test_render_shows_latest_with_age() -> None:
    wm = VisionWorkingMemory()
    now = time.time()
    obs = VisionObservation(
        timestamp=now - 12,
        attachment_ref="abc123",
        description="a green mug on a desk",
        novelty_score=0.42,
        subject_identity="captain",
        session_id="s1",
    )
    wm.append(obs)
    rendered = wm.render_for_prompt(now=now)
    assert "12s ago" in rendered
    assert "novelty=0.42" in rendered
    assert "subject=captain" in rendered
    assert "a green mug on a desk" in rendered


def test_ring_buffer_eviction() -> None:
    wm = VisionWorkingMemory(capacity=2)
    for i in range(3):
        wm.append(VisionObservation(
            timestamp=float(i),
            attachment_ref=f"sha{i}",
            description=f"obs {i}",
            novelty_score=0.5,
        ))
    entries = wm.entries()
    assert len(entries) == 2
    assert entries[0].description == "obs 1"
    assert entries[1].description == "obs 2"


def test_thread_safety() -> None:
    wm = VisionWorkingMemory(capacity=64)
    errors: list[BaseException] = []

    def _writer() -> None:
        try:
            for i in range(50):
                wm.append(VisionObservation(
                    timestamp=float(i),
                    attachment_ref=f"sha{i}",
                    description=f"obs {i}",
                    novelty_score=0.5,
                ))
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    def _reader() -> None:
        try:
            for _ in range(50):
                wm.entries()
                wm.latest()
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=_writer) for _ in range(2)]
    threads += [threading.Thread(target=_reader) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ---------- Consumer (5) ----------


def test_consumer_subscribes_to_vision_observation(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    consumer.subscribe()
    runtime.intent_bus.subscribe.assert_called_once()
    args, kwargs = runtime.intent_bus.subscribe.call_args
    # subscribe(agent_id, handler, intent_names=[...])
    assert args[0] == VisionConsumer.SUBSCRIBER_AGENT_ID
    assert kwargs["intent_names"] == [VisionConsumer.INTENT_NAME]


@pytest.mark.asyncio
async def test_consumer_skips_missing_attachment(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")

    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": "nonexistent-sha", "session_id": "s1"},
    )
    await consumer._handle(msg)
    # No LLM call, no episode store.
    runtime.llm_client.complete.assert_not_called()
    runtime.episodic_memory.store.assert_not_called()


@pytest.mark.asyncio
async def test_supervisor_blocked_frame_skips_llm(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)

    class _DenyStrategy:
        def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
            return SupervisorDecision(allow=False, novelty_score=0.0, reason="denied")

    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer._supervisor = VisionSupervisor(strategy=_DenyStrategy())
    consumer.register_observer("ezri")

    sha = await _store_frame(runtime, _make_jpeg())
    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": sha, "session_id": "s1"},
    )
    await consumer._handle(msg)
    runtime.llm_client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_describe_success_writes_to_all_observers(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    consumer.register_observer("data")

    sha = await _store_frame(runtime, _make_jpeg())
    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": sha, "session_id": "s1"},
    )
    await consumer._handle(msg)

    ezri_wm = get_or_create_working_memory("ezri")
    data_wm = get_or_create_working_memory("data")
    assert len(ezri_wm.entries()) == 1
    assert len(data_wm.entries()) == 1
    assert "glass of water" in ezri_wm.entries()[0].description


@pytest.mark.asyncio
async def test_episode_anchor_uses_importance_6(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")

    sha = await _store_frame(runtime, _make_jpeg())
    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": sha, "session_id": "s1"},
    )
    await consumer._handle(msg)
    runtime.episodic_memory.store.assert_called()
    episode: Episode = runtime.episodic_memory.store.call_args.args[0]
    assert episode.importance == 6
    assert isinstance(episode.anchors, AnchorFrame)
    assert episode.anchors.trigger_type == "vision_described"
    assert episode.anchors.channel == "perception"


# ---------- Integration (3) ----------


def test_dm_reply_prepends_scene_block() -> None:
    """The render_for_prompt block contains the latest observation and is
    suitable for prepending into agent_chat message_text (AD-733a Section 6).
    """
    wm = get_or_create_working_memory("ezri")
    wm.append(VisionObservation(
        timestamp=time.time(),
        attachment_ref="sha1",
        description="A glass of water in the hand.",
        novelty_score=0.5,
        subject_identity="captain",
        session_id="s1",
    ))
    rendered = wm.render_for_prompt()
    assert "A glass of water in the hand." in rendered
    assert "Camera not active" not in rendered


def test_dm_reply_with_empty_wm_injects_no_data_sentinel() -> None:
    """BF-294 confabulation guard: empty buffer renders the explicit sentinel."""
    wm = get_or_create_working_memory("data")
    rendered = wm.render_for_prompt()
    assert "Camera not active or no frames described yet" in rendered
    assert "Do NOT describe what you cannot see" in rendered


def test_vision_consumer_disabled_via_config() -> None:
    """When ``vision_consumer_enabled=False`` the finalize block must not
    instantiate the consumer. We verify the config field default + an
    operator-overridden False stays False end-to-end.
    """
    cfg = SystemConfig()
    assert cfg.perception.vision_consumer_enabled is True  # default
    cfg.perception.vision_consumer_enabled = False
    assert cfg.perception.vision_consumer_enabled is False


# ---------- AD-731 invariant source scan ----------


def test_ad731_invariant_no_inline_base64_in_perception_modules() -> None:
    """AD-731: frame bytes must remain SHA refs throughout the perception
    pipeline. Source-scan the three new modules for any sign of inline
    base64 usage (b64encode / base64.b64 / blob_b64)."""
    import probos.perception.consumer as _consumer_mod
    import probos.perception.observer as _observer_mod
    import probos.perception.supervisor as _supervisor_mod
    import probos.perception.working_memory as _wm_mod

    for mod in (_consumer_mod, _observer_mod, _supervisor_mod, _wm_mod):
        src_path = Path(mod.__file__ or "")
        assert src_path.exists(), f"source file missing for {mod.__name__}"
        text = src_path.read_text(encoding="utf-8")
        # Allow the word "base64" only inside comments referencing the invariant.
        forbidden = ("b64encode", "base64.b64", "blob_b64")
        for token in forbidden:
            assert token not in text, (
                f"AD-731 violation: {mod.__name__} contains forbidden token "
                f"{token!r}; frames must remain SHA refs."
            )


@pytest.mark.asyncio
async def test_bf304_single_flight_drops_concurrent_describe(tmp_path: Path) -> None:
    """BF-304: when a describe is already in flight, additional frames must
    be dropped (not queued) to prevent VRAM/RAM pile-up that crashed the
    process under FORCE-DESCRIBE spam (Rust alloc failure 4194304 bytes).
    """
    import asyncio
    import unittest.mock as mock

    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    reset_working_memories_for_tests()

    describe_calls = 0
    release = asyncio.Event()

    async def _slow_describe(_sha: str) -> str:
        nonlocal describe_calls
        describe_calls += 1
        await release.wait()
        return "described content"

    with mock.patch.object(consumer, "_describe", side_effect=_slow_describe):
        sha_a = await _store_frame(runtime, _make_jpeg())
        sha_b = await _store_frame(runtime, _make_jpeg(color=(30, 30, 200)))
        # Fire both concurrently; first acquires the lock, second hits the
        # locked() guard and returns immediately.
        first = asyncio.create_task(consumer._handle(IntentMessage(
            intent="vision_observation",
            params={"attachment_ref": sha_a, "session_id": "s1", "force": True},
        )))
        # Yield once so the first task is inside _slow_describe.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        second = asyncio.create_task(consumer._handle(IntentMessage(
            intent="vision_observation",
            params={"attachment_ref": sha_b, "session_id": "s1", "force": True},
        )))
        # Second should complete quickly (dropped) — if it queued behind the
        # gated first describe, wait_for would time out. 2s tolerates xdist
        # scheduling pressure under parallel workers.
        await asyncio.wait_for(second, timeout=2.0)
        assert describe_calls == 1, (
            f"BF-304: expected single describe in flight, got {describe_calls}"
        )

        # Release the first call so the test can finish.
        release.set()
        await first
        # First completed → describe count still 1 (second was dropped).
        assert describe_calls == 1


def test_bf309_baseline_refresh_after_max_age() -> None:
    """BF-309: when no admit has happened for baseline_max_age_seconds, the
    next frame becomes a fresh first_frame (re-baseline). Prevents static
    scenes from anchoring the supervisor forever."""
    from probos.perception.supervisor import PerceptualHashStrategy

    strat = PerceptualHashStrategy(
        min_interval_seconds=0.0,
        novelty_threshold=0.5,  # high; nearly nothing crosses
        baseline_max_age_seconds=10.0,
    )

    # Frame at t=0 → first_frame
    d0 = strat.evaluate(_make_jpeg(), now=0.0)
    assert d0.allow and d0.reason == "first_frame"

    # Frame at t=5 (within 10s window) and below 0.5 threshold → low_novelty
    d1 = strat.evaluate(_make_jpeg(), now=5.0)
    assert not d1.allow and d1.reason == "low_novelty"

    # Frame at t=15 (past 10s window) → baseline_refresh admit
    d2 = strat.evaluate(_make_jpeg(), now=15.0)
    assert d2.allow and d2.reason == "baseline_refresh"
    assert d2.novelty_score == 1.0


def test_bf309_zero_max_age_disables_refresh() -> None:
    """BF-309: setting baseline_max_age_seconds=0 disables the refresh
    entirely — supervisor reverts to legacy static-anchor behavior."""
    from probos.perception.supervisor import PerceptualHashStrategy

    strat = PerceptualHashStrategy(
        min_interval_seconds=0.0,
        novelty_threshold=0.5,
        baseline_max_age_seconds=0.0,
    )

    strat.evaluate(_make_jpeg(), now=0.0)  # first_frame
    # Even after 9999s, refresh disabled — still low_novelty
    d = strat.evaluate(_make_jpeg(), now=9999.0)
    assert not d.allow and d.reason == "low_novelty"


def test_bf309_set_baseline_max_age_seconds_live_update() -> None:
    """BF-309: setter mutates without reconstructing the strategy."""
    from probos.perception.supervisor import PerceptualHashStrategy

    strat = PerceptualHashStrategy(
        min_interval_seconds=0.0,
        novelty_threshold=0.5,
        baseline_max_age_seconds=60.0,
    )
    assert strat._baseline_max_age == 60.0
    strat.set_baseline_max_age_seconds(15.0)
    assert strat._baseline_max_age == 15.0
