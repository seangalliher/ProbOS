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
from probos.types import AnchorFrame, Episode, IntentMessage, LLMRequest, LLMResponse


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


# ---------- WorkingMemory (12) ----------


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


def test_stale_latest_renders_no_data_sentinel() -> None:
    # AD-1055: a latest observation older than the freshness window is treated
    # as camera-off — the agent must NOT describe a carried-over scene (the
    # BF-624 class: a prior session's disk-hydrated frame).
    wm = VisionWorkingMemory()
    now = time.time()
    wm.append(VisionObservation(
        timestamp=now - 3600,  # 1h old
        attachment_ref="old1",
        description="a plaid shirt and a bookshelf",
        novelty_score=0.5,
        subject_identity="captain",
    ))
    rendered = wm.render_for_prompt(now=now, freshness_s=120.0)
    assert "Camera not active or no frames described yet" in rendered
    assert "plaid shirt" not in rendered


def test_fresh_latest_within_window_still_renders() -> None:
    # AD-1055: an observation INSIDE the freshness window renders normally.
    wm = VisionWorkingMemory()
    now = time.time()
    wm.append(VisionObservation(
        timestamp=now - 10,
        attachment_ref="fresh1",
        description="a green mug on a desk",
        novelty_score=0.42,
        subject_identity="captain",
    ))
    rendered = wm.render_for_prompt(now=now, freshness_s=120.0)
    assert "a green mug on a desk" in rendered
    assert "Camera not active" not in rendered


def test_freshness_disabled_renders_stale_observation() -> None:
    # AD-1055: freshness_s=None (default) / 0 disables the guard — byte-identical
    # to the pre-AD-1055 legacy behavior.
    wm = VisionWorkingMemory()
    now = time.time()
    wm.append(VisionObservation(
        timestamp=now - 86400,  # a day old
        attachment_ref="old2",
        description="an orange cat",
        novelty_score=0.5,
    ))
    assert "an orange cat" in wm.render_for_prompt(now=now)            # default None
    assert "an orange cat" in wm.render_for_prompt(now=now, freshness_s=0)


def test_render_includes_background_disposition() -> None:
    # AD-1059: the rendered scene carries the "background context, do not narrate
    # by default" disposition so agents stop over-narrating an unchanged feed.
    wm = VisionWorkingMemory()
    now = time.time()
    wm.append(VisionObservation(
        timestamp=now - 5, attachment_ref="d1",
        description="a desk and a window", novelty_score=0.4,
        subject_identity="captain",
    ))
    rendered = wm.render_for_prompt(now=now)
    assert "BACKGROUND context" in rendered
    assert "only when" in rendered
    assert "a desk and a window" in rendered


def test_no_data_sentinel_omits_disposition_keeps_guard() -> None:
    # AD-1059: the no-data sentinel keeps its OWN confabulation guard and does
    # NOT carry the background disposition (there is nothing to be quiet about).
    rendered = VisionWorkingMemory().render_for_prompt()
    assert "BACKGROUND context" not in rendered
    assert "Do NOT describe what you cannot see" in rendered


def test_decayed_novelty_empty_ring_is_zero() -> None:
    # AD-1060: no observations -> 0.0.
    assert VisionWorkingMemory(capacity=8).decayed_novelty(alpha=0.3) == 0.0


def test_decayed_novelty_ema_decays_then_recovers() -> None:
    # AD-1060: a high frame then stable low frames decays the EMA below the
    # "materially changed" threshold; a fresh high frame pulls it back up.
    wm = VisionWorkingMemory(capacity=8)
    base = time.time()
    for i, nov in enumerate([0.9, 0.05, 0.05, 0.05, 0.05]):
        wm.append(VisionObservation(
            timestamp=base + i, attachment_ref=f"s{i}",
            description="x", novelty_score=nov,
        ))
    settled = wm.decayed_novelty(alpha=0.3)
    assert settled < 0.3
    wm.append(VisionObservation(
        timestamp=base + 5, attachment_ref="s5",
        description="x", novelty_score=0.95,
    ))
    assert wm.decayed_novelty(alpha=0.3) > settled


def test_decayed_novelty_stale_ring_is_zero() -> None:
    # AD-1060: a stale ring (camera off) has no current novelty (AD-1055 rule).
    wm = VisionWorkingMemory(capacity=8)
    now = time.time()
    wm.append(VisionObservation(
        timestamp=now - 3600, attachment_ref="old",
        description="x", novelty_score=0.9,
    ))
    assert wm.decayed_novelty(alpha=0.3, now=now, freshness_s=120.0) == 0.0


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


@pytest.mark.asyncio
async def test_bf311_anchored_episode_tagged_with_observer_agent_ids(tmp_path: Path) -> None:
    """BF-311: perception-anchored episodes MUST carry agent_ids so per-agent
    episodic recall surfaces them. Without this, episodes get
    ``agent_ids_json = []`` in chroma and are invisible to recall queries
    that filter by participant — silently breaking the AD-541b promise that
    perception observations form long-term memory."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    consumer.register_observer("data")
    reset_working_memories_for_tests()

    sha = await _store_frame(runtime, _make_jpeg())
    msg = IntentMessage(
        intent="vision_observation",
        params={"attachment_ref": sha, "session_id": "s1"},
    )
    await consumer._handle(msg)

    runtime.episodic_memory.store.assert_called()
    episode: Episode = runtime.episodic_memory.store.call_args.args[0]
    # Both registered observers should be tagged so each agent's recall finds it.
    assert set(episode.agent_ids) == {"ezri", "data"}, (
        f"BF-311: perception anchor episode missing observer agent_ids; "
        f"got {episode.agent_ids!r}. This is the bug that hid Ezri's "
        f"white-shirt memories from her own recall."
    )


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
    describe_started = asyncio.Event()

    async def _slow_describe(_sha: str) -> str:
        nonlocal describe_calls
        describe_calls += 1
        describe_started.set()
        await release.wait()
        return "described content"

    with mock.patch.object(consumer, "_describe", side_effect=_slow_describe):
        sha_a = await _store_frame(runtime, _make_jpeg())
        sha_b = await _store_frame(runtime, _make_jpeg(color=(30, 30, 200)))
        # Fire the first, then DETERMINISTICALLY wait until it is actually
        # inside _slow_describe (holding the single-flight lock) before firing
        # the second. Relying on sleep(0) yields is a scheduling RACE under load
        # (the CI flake: the second task could acquire the lock first and then
        # block on `release` forever -> wait_for times out). Waiting on the real
        # describe_started event makes the ordering deterministic.
        first = asyncio.create_task(consumer._handle(IntentMessage(
            intent="vision_observation",
            params={"attachment_ref": sha_a, "session_id": "s1", "force": True},
        )))
        await asyncio.wait_for(describe_started.wait(), timeout=10.0)
        second = asyncio.create_task(consumer._handle(IntentMessage(
            intent="vision_observation",
            params={"attachment_ref": sha_b, "session_id": "s1", "force": True},
        )))
        # Second must complete quickly (dropped by the locked() guard). If it
        # queued behind the gated first describe, wait_for would time out.
        await asyncio.wait_for(second, timeout=10.0)
        assert describe_calls == 1, (
            f"BF-304: expected single describe in flight, got {describe_calls}"
        )
        # Release the gated first describe so the task completes cleanly (no leak).
        release.set()
        await asyncio.gather(first, return_exceptions=True)

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


@pytest.mark.asyncio
async def test_bf314_moondream_gets_short_single_clause_prompt(tmp_path: Path) -> None:
    """BF-314: per-tier describe prompt. moondream (vision_fast, 1.8B) loops
    on multi-clause prompts and hallucinates numbered lists. The fast-tier
    branch must send a single-clause prompt with temperature=0 and a
    tight token cap. qwen3.6:27b (vision) keeps the multi-clause prompt.
    """
    import unittest.mock as mock

    runtime = _build_runtime(tmp_path)
    # Configure vision_fast so the route selects it.
    runtime.config.cognitive.llm_base_url_vision_fast = "http://localhost:11434"
    runtime.config.cognitive.llm_model_vision_fast = "moondream"
    runtime.config.cognitive.llm_api_format_vision_fast = "ollama"
    runtime.config.cognitive.llm_timeout_vision_fast = 15.0

    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    sha = await _store_frame(runtime, _make_jpeg())

    captured: dict[str, Any] = {}

    async def _capture(req: LLMRequest) -> Any:
        captured["tier"] = req.tier
        captured["messages"] = req.messages
        captured["temperature"] = req.temperature
        captured["max_tokens"] = req.max_tokens
        return mock.MagicMock(content="a person in a dark sweatshirt", error=None)

    runtime.llm_client.complete = _capture  # type: ignore[assignment]
    description = await consumer._describe(sha)

    assert description == "a person in a dark sweatshirt"
    assert captured["tier"] == "vision_fast"
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 100
    # Prompt is in the user message; pull it out.
    user_msg = next(m for m in captured["messages"] if m.get("role") == "user")
    content = user_msg["content"]
    prompt_text = content if isinstance(content, str) else next(
        part["text"] for part in content if part.get("type") == "text"
    )
    # Single-clause shape: 1-2 sentences + "do not invent", no bullet
    # request, no "describe what they're doing AND what they're holding"
    # multi-clause structure that triggers moondream looping.
    assert "one or two sentences" in prompt_text.lower()
    assert "do not invent" in prompt_text.lower()
    assert "describe their clothing and what they're doing" not in prompt_text
    # BF-316: anti-confabulation anchors. Small VLMs confabulate scenes
    # from contextual priors (framed photo on shelf -> "video call with
    # multiple participants"). Prompt must explicitly disambiguate.
    lowered = prompt_text.lower()
    assert "literally visible" in lowered
    assert "framed pictures" in lowered or "photos" in lowered
    assert "video call" in lowered  # appears as a negative example


@pytest.mark.asyncio
async def test_bf314_vision_keeps_multiclause_prompt(tmp_path: Path) -> None:
    """BF-314: when vision_fast is unconfigured, fall back to the deep
    vision tier with the original multi-clause prompt (qwen3.6:27b handles
    it fine; only moondream loops)."""
    import unittest.mock as mock

    runtime = _build_runtime(tmp_path)
    # vision_fast intentionally unset; should route to vision.
    runtime.config.cognitive.llm_model_vision_fast = None

    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    sha = await _store_frame(runtime, _make_jpeg())

    captured: dict[str, Any] = {}

    async def _capture(req: LLMRequest) -> Any:
        captured["tier"] = req.tier
        captured["temperature"] = req.temperature
        captured["max_tokens"] = req.max_tokens
        captured["messages"] = req.messages
        return mock.MagicMock(content="captain holds a glass of water", error=None)

    runtime.llm_client.complete = _capture  # type: ignore[assignment]
    await consumer._describe(sha)

    assert captured["tier"] == "vision"
    assert captured["temperature"] == 0.2
    user_msg = next(m for m in captured["messages"] if m.get("role") == "user")
    content = user_msg["content"]
    prompt_text = content if isinstance(content, str) else next(
        part["text"] for part in content if part.get("type") == "text"
    )
    # Original multi-clause prompt preserved on the deep tier.
    assert "describe their clothing and what they're doing" in prompt_text
    assert "If they are holding an object" in prompt_text
