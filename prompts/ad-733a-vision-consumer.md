# AD-733a — VisionConsumer + Supervisor + Working Memory + DM context injection

**Wave:** 171
**Closes:** [#665](https://github.com/seangalliher/ProbOS/issues/665)
**Depends on:** AD-733 v1 (Wave 170 — `vision_observation` intent shipped); AD-732 vision tier; AD-573 AgentWorkingMemory.
**Estimated tests:** +18 pytest (+0 vitest — UI deferred to BF-298)
**Risk:** medium-high — adds a runtime-owned background consumer that calls the vision LLM on a budget. Tier-2 log-and-degrade throughout.

---

## Problem

Wave 170 (AD-733 v1) shipped the wire shape: HXI captures frames → `POST /api/perception/camera/frame` → AttachmentStore (AD-731 ref) → `IntentMessage(intent="vision_observation")` broadcast on the bus. **Nothing consumes the intent.** Captain holds up a glass of water; Ezri sees nothing.

This prompt closes the loop with three new modules wired together as the **NeuralCompanion three-tier pattern (MIT, absorbed)**:

```
VisionSource     (existing — routers/perception.py uploads frames)
  ↓ vision_observation intents (AD-731 ref, no inline bytes)
VisionSupervisor (NEW — perception/supervisor.py — gate: is this frame worth an LLM call?)
  ↓ flagged frames
VisionConsumer   (NEW — perception/consumer.py — calls vision LLM, writes to working memory)
  ↓ updates
VisionWorkingMemory (NEW — perception/working_memory.py — per-agent ring buffer)
  ↓ injected before LLM call
agent_chat       (existing — routers/agents.py — prepends current-scene block to message_text)
```

Plus a confabulation guard: when the buffer is empty, the prompt explicitly says **"no current visual data"** rather than silently omitting context (BF-294 lesson — Ezri confabulated avatar filenames).

---

## Solution

### Section 1: `src/probos/perception/supervisor.py` (NEW)

Per-frame admission gate. v1 strategy: temporal throttle + perceptual aHash diff. Pluggable Protocol so AD-742d can swap.

```python
"""AD-733a: VisionSupervisor — frame-admission gate for vision LLM calls.

NeuralCompanion pattern (MIT, absorbed): VisionSource → VisionSupervisor →
VisionConsumer. The supervisor answers "is this frame worth an LLM call?"
without itself spending an LLM call. v1 strategy: temporal throttle (min
seconds between LLM calls) + perceptual aHash diff (32-bit hash on a 8x8
downscaled grayscale, Hamming distance > threshold).

AD-742d forward marker: pluggable Strategy Protocol so motion / CLIP /
scene-change classifier can replace this in future. v1 ships
PerceptualHashStrategy as the default; the Protocol is the public surface.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorDecision:
    """Result of one supervisor pass over a frame."""
    allow: bool
    novelty_score: float  # 0.0 (identical to last) → 1.0 (totally novel)
    reason: str           # "throttled" | "low_novelty" | "first_frame" | "novel"


@runtime_checkable
class SupervisorStrategy(Protocol):
    """Pluggable Protocol — AD-742d will add motion / CLIP / classifier variants."""
    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision: ...


class PerceptualHashStrategy:
    """v1 default — aHash diff + temporal throttle. Pure Python; no new deps."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = 5.0,
        novelty_threshold: float = 0.15,
    ) -> None:
        self._min_interval = float(min_interval_seconds)
        self._threshold = float(novelty_threshold)
        self._last_allow_at: float = 0.0
        self._last_hash: int | None = None

    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
        # Tier-2: if hash computation fails (corrupt JPEG, PIL not available),
        # honest-degrade to "allow first frame, then throttle" — never raise.
        try:
            current_hash = _ahash_jpeg_bytes(frame_bytes)
        except Exception:
            logger.debug("AD-733a: aHash failed, defaulting to throttle-only", exc_info=True)
            current_hash = None

        if self._last_hash is None or self._last_allow_at == 0.0:
            self._last_hash = current_hash
            self._last_allow_at = now
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="first_frame")

        elapsed = now - self._last_allow_at
        if elapsed < self._min_interval:
            return SupervisorDecision(allow=False, novelty_score=0.0, reason="throttled")

        if current_hash is None or self._last_hash is None:
            # Hash unavailable → allow (we already passed the throttle gate)
            self._last_allow_at = now
            self._last_hash = current_hash
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="novel")

        # 64-bit aHash → bit-difference / 64 = novelty in [0,1]
        diff_bits = bin(current_hash ^ self._last_hash).count("1")
        novelty = diff_bits / 64.0

        if novelty < self._threshold:
            return SupervisorDecision(allow=False, novelty_score=novelty, reason="low_novelty")

        self._last_allow_at = now
        self._last_hash = current_hash
        return SupervisorDecision(allow=True, novelty_score=novelty, reason="novel")


def _ahash_jpeg_bytes(jpeg_bytes: bytes) -> int:
    """Average-hash 64-bit. Uses Pillow if available; raises otherwise."""
    from io import BytesIO
    from PIL import Image  # Pillow is already a transitive dep via image processing

    img = Image.open(BytesIO(jpeg_bytes)).convert("L").resize((8, 8), Image.NEAREST)
    pixels = list(img.getdata())
    avg = sum(pixels) / 64.0
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= 1 << i
    return bits


class VisionSupervisor:
    """Per-(runtime+session) admission gate wrapping a SupervisorStrategy."""

    def __init__(self, strategy: SupervisorStrategy | None = None) -> None:
        self._strategy = strategy or PerceptualHashStrategy()

    def admit(self, frame_bytes: bytes) -> SupervisorDecision:
        return self._strategy.evaluate(frame_bytes, now=time.monotonic())


__all__ = ["VisionSupervisor", "SupervisorDecision", "SupervisorStrategy", "PerceptualHashStrategy"]
```

### Section 2: `src/probos/perception/working_memory.py` (NEW)

Per-agent ring buffer of vision observations, with a render-for-prompt method.

```python
"""AD-733a: VisionWorkingMemory — per-agent ring buffer of vision observations.

The hot buffer used for prompt-context injection. Capacity 8 by default;
configurable via PerceptionConfig.working_memory_size. In-RAM only —
AD-742f forward marker for persistence across restart. AD-541b-anchored
episodes ARE persisted (those are the canonical long-term memory); this
buffer is the working-set projection.

Confabulation guard (BF-294 lesson): callers MUST treat empty buffer as
"no current visual data" rather than silently omitting context. The
`render_for_prompt` method returns the explicit empty-state string.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock


@dataclass(frozen=True)
class VisionObservation:
    """One supervisor-flagged + LLM-described frame."""
    timestamp: float
    attachment_ref: str        # SHA-256 of frame bytes in AttachmentStore (AD-731)
    description: str           # vision LLM output, truncated to ~400 chars
    novelty_score: float       # 0.0–1.0 from supervisor
    subject_identity: str = "unknown"  # "captain" | "unknown" | "other" — AD-733b populates
    session_id: str = ""


class VisionWorkingMemory:
    """Thread-safe per-agent ring buffer. One instance per agent_id per runtime."""

    def __init__(self, *, capacity: int = 8) -> None:
        self._buf: deque[VisionObservation] = deque(maxlen=capacity)
        self._lock = Lock()

    def append(self, obs: VisionObservation) -> None:
        with self._lock:
            self._buf.append(obs)

    def entries(self) -> list[VisionObservation]:
        with self._lock:
            return list(self._buf)

    def latest(self) -> VisionObservation | None:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def render_for_prompt(self, *, now: float | None = None) -> str:
        """Render the buffer for LLM prompt injection.

        Confabulation guard: when empty, returns a non-empty string that
        explicitly says no visual data is available. The agent's prompt
        builder MUST receive a clear "no data" signal rather than an
        empty string the agent might fill in from imagination.
        """
        entries = self.entries()
        if not entries:
            return (
                "--- Current Visual Context ---\n"
                "Camera not active or no frames described yet. "
                "Do NOT describe what you cannot see.\n"
                "--- End Visual Context ---"
            )

        now_ts = time.time() if now is None else now
        latest = entries[-1]
        age_s = max(0.0, now_ts - latest.timestamp)
        age_str = _format_age(age_s)

        lines = [
            "--- Current Visual Context ---",
            f"Most recent observation ({age_str} ago, novelty={latest.novelty_score:.2f}, "
            f"subject={latest.subject_identity}):",
            f"  {latest.description}",
        ]
        if len(entries) > 1:
            lines.append(f"Prior {len(entries) - 1} observation(s) in working memory.")
        lines.append("--- End Visual Context ---")
        return "\n".join(lines)


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


__all__ = ["VisionWorkingMemory", "VisionObservation"]
```

### Section 3: `src/probos/perception/consumer.py` (NEW)

Subscribes to `vision_observation` intents, runs supervisor, calls vision LLM, writes to per-agent working memory, anchors an episode.

```python
"""AD-733a: VisionConsumer — subscribes to vision_observation intents,
runs the supervisor gate, calls the vision LLM on flagged frames, writes
results to per-agent VisionWorkingMemory and anchors an Episode.

Cost discipline: the supervisor enforces a per-session min-interval floor
(default 5s) so a 1 fps camera produces at most 0.2 fps of vision LLM
calls. Captain can tune via PerceptionConfig.vision_min_interval_seconds.

AD-731 invariant preserved end-to-end: the consumer reads the frame
bytes from AttachmentStore by SHA, never from inline base64 in the
intent. The vision LLM call uses build_multimodal_messages from
vision_dispatch (BF-268 OpenAI-shape resolver).

Tier-2 log-and-degrade: every failure (supervisor exception, LLM error,
episode store failure) logs WARNING and skips that frame. The consumer
never raises into the intent bus.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from probos.types import (
    AnchorFrame,
    Episode,
    IntentMessage,
    IntentResult,
    LLMRequest,
)

logger = logging.getLogger(__name__)


# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
# Module-scoped because the consumer is runtime-singleton — one runtime
# owns one camera and dispatches to N agents.
_WORKING_MEMORIES: dict[str, Any] = {}  # agent_id → VisionWorkingMemory


def get_or_create_working_memory(agent_id: str, *, capacity: int = 8) -> Any:
    """Return the VisionWorkingMemory for an agent, creating on first access."""
    from probos.perception.working_memory import VisionWorkingMemory
    if agent_id not in _WORKING_MEMORIES:
        _WORKING_MEMORIES[agent_id] = VisionWorkingMemory(capacity=capacity)
    return _WORKING_MEMORIES[agent_id]


def reset_working_memories_for_tests() -> None:
    """Test-only — clears the module-level WM registry."""
    _WORKING_MEMORIES.clear()


class VisionConsumer:
    """Runtime-owned consumer that bridges vision_observation → working memory."""

    INTENT_NAME = "vision_observation"
    SUBSCRIBER_AGENT_ID = "perception.vision_consumer"

    def __init__(
        self,
        runtime: Any,
        *,
        min_interval_seconds: float = 5.0,
        novelty_threshold: float = 0.15,
        working_memory_capacity: int = 8,
        vision_tier: str = "vision",
        max_describe_tokens: int = 220,
        describe_timeout_s: float = 30.0,
    ) -> None:
        from probos.perception.supervisor import (
            PerceptualHashStrategy,
            VisionSupervisor,
        )

        self._runtime = runtime
        self._supervisor = VisionSupervisor(
            strategy=PerceptualHashStrategy(
                min_interval_seconds=min_interval_seconds,
                novelty_threshold=novelty_threshold,
            )
        )
        self._wm_capacity = working_memory_capacity
        self._tier = vision_tier
        self._max_tokens = max_describe_tokens
        self._timeout = describe_timeout_s
        # Set of agent_ids that should receive observations. For v1 this
        # is "every crew agent with vision_capable=True". The consumer
        # writes to each such agent's WorkingMemory on every flagged frame.
        self._observer_agent_ids: set[str] = set()

    def register_observer(self, agent_id: str) -> None:
        self._observer_agent_ids.add(agent_id)

    def subscribe(self) -> None:
        """Register on the intent bus. Idempotent at the bus level."""
        self._runtime.intent_bus.subscribe(
            self.SUBSCRIBER_AGENT_ID,
            self._handle,
            intent_names=[self.INTENT_NAME],
        )
        logger.info("AD-733a: VisionConsumer subscribed to %s", self.INTENT_NAME)

    async def _handle(self, msg: IntentMessage) -> IntentResult | None:
        """Bus handler — supervisor-gate, LLM-describe, WM-write, episode-anchor."""
        if msg.intent != self.INTENT_NAME:
            return None
        try:
            await self._process(msg)
        except Exception:
            logger.warning(
                "AD-733a: VisionConsumer dropped frame "
                "(session=%s); exception in _process",
                msg.params.get("session_id", "")[:8],
                exc_info=True,
            )
        # Fire-and-forget on the bus — return None so the dispatcher
        # treats this as "no reply needed". Matches AD-733 v1 semantics.
        return None

    async def _process(self, msg: IntentMessage) -> None:
        sha = msg.params.get("attachment_ref")
        session_id = str(msg.params.get("session_id", ""))
        if not sha or not isinstance(sha, str):
            logger.debug("AD-733a: vision_observation missing attachment_ref; skipping")
            return

        # 1) Load bytes from AttachmentStore (AD-731 invariant).
        from probos.routers.chat import _get_attachment_store
        store = _get_attachment_store(self._runtime)
        frame_bytes = await store.read(sha)
        if not frame_bytes:
            logger.warning("AD-733a: attachment %s missing; skipping frame", sha[:8])
            return

        # 2) Supervisor gate.
        decision = self._supervisor.admit(frame_bytes)
        if not decision.allow:
            logger.debug(
                "AD-733a: supervisor dropped frame sha=%s reason=%s",
                sha[:8], decision.reason,
            )
            return

        # 3) Vision LLM describe.
        description = await self._describe(sha)
        if not description:
            logger.info("AD-733a: vision LLM returned empty for sha=%s", sha[:8])
            return

        # 4) Write to every registered observer's WorkingMemory.
        from probos.perception.working_memory import VisionObservation
        obs = VisionObservation(
            timestamp=time.time(),
            attachment_ref=sha,
            description=description[:400],
            novelty_score=decision.novelty_score,
            subject_identity="unknown",  # AD-733b populates
            session_id=session_id,
        )
        for agent_id in list(self._observer_agent_ids):
            wm = get_or_create_working_memory(agent_id, capacity=self._wm_capacity)
            wm.append(obs)

        # 5) Anchor an episode (AD-541b — importance=6, lower than camera_began=8).
        await self._anchor_episode(sha, description, decision.novelty_score, session_id)

    async def _describe(self, sha: str) -> str:
        """Call the vision LLM on a single frame. Returns description or empty string."""
        try:
            from probos.cognitive.vision_dispatch import build_multimodal_messages
            from probos.routers.chat import _get_attachment_store
            store = _get_attachment_store(self._runtime)

            async def _mime_lookup(content_hash: str) -> str | None:
                return await store.mime_for(content_hash)

            messages, image_ids, _per = await build_multimodal_messages(
                prompt=(
                    "Briefly describe what you see in this frame. "
                    "If a person is visible, describe their clothing and what they're doing. "
                    "If they are holding an object, name and describe the object. "
                    "Keep the description under 80 words. Do not speculate beyond what is visible."
                ),
                attachment_ids=[sha],
                store=store,
                mime_lookup=_mime_lookup,
                text_extraction_max_bytes=0,
                pdf_extraction_enabled=False,
            )
            if not image_ids:
                return ""

            request = LLMRequest(
                prompt="",
                messages=messages,
                tier=self._tier,
                max_tokens=self._max_tokens,
                temperature=0.2,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            return (response.content or "").strip()
        except Exception:
            logger.warning("AD-733a: vision LLM describe failed for sha=%s", sha[:8], exc_info=True)
            return ""

    async def _anchor_episode(
        self, sha: str, description: str, novelty: float, session_id: str,
    ) -> None:
        episodic = getattr(self._runtime, "episodic_memory", None)
        if episodic is None:
            return
        try:
            episode = Episode(
                timestamp=time.time(),
                user_input="",
                outcomes=[{
                    "intent": "vision_observation",
                    "success": True,
                    "session_id": session_id,
                    "attachment_ref": sha,
                    "novelty_score": novelty,
                }],
                reflection=f"Vision observation: {description}",
                source="direct",
                importance=6,
                anchors=AnchorFrame(
                    channel="perception",
                    trigger_type="vision_described",
                    trigger_agent="vision_consumer",
                ),
            )
            await episodic.store(episode)
        except Exception:
            logger.warning(
                "AD-733a: episode anchor failed for sha=%s; observation is in "
                "working memory but not in long-term store",
                sha[:8], exc_info=True,
            )


__all__ = ["VisionConsumer", "get_or_create_working_memory", "reset_working_memories_for_tests"]
```

### Section 4: `src/probos/config.py` — extend `PerceptionConfig`

Add five fields. SEARCH for the existing `PerceptionConfig` (verified line ~1920):

```
===SEARCH===
class PerceptionConfig(BaseModel):
    """AD-733: visual sensor input from operator-side capture devices."""

    enabled: bool = False
    """Master switch for the entire perception subsystem."""

    camera: CameraStreamConfig = Field(default_factory=CameraStreamConfig)

    camera_max_fps_server: int = Field(default=4, ge=1, le=10,
        description="Server-side hard cap on frame ingestion rate per session.",
    )

    frame_max_size_bytes: int = Field(default=512 * 1024, ge=4096, le=5 * 1024 * 1024,
        description="Reject frame uploads larger than this. Default 512 KB.",
    )
===REPLACE===
class PerceptionConfig(BaseModel):
    """AD-733: visual sensor input from operator-side capture devices."""

    enabled: bool = False
    """Master switch for the entire perception subsystem."""

    camera: CameraStreamConfig = Field(default_factory=CameraStreamConfig)

    camera_max_fps_server: int = Field(default=4, ge=1, le=10,
        description="Server-side hard cap on frame ingestion rate per session.",
    )

    frame_max_size_bytes: int = Field(default=512 * 1024, ge=4096, le=5 * 1024 * 1024,
        description="Reject frame uploads larger than this. Default 512 KB.",
    )

    # AD-733a (Wave 171): VisionConsumer cost-discipline + buffer sizing.
    vision_consumer_enabled: bool = Field(default=True,
        description="Run the VisionConsumer that calls the vision LLM on supervisor-flagged frames.",
    )
    vision_min_interval_seconds: float = Field(default=5.0, ge=1.0, le=120.0,
        description="Minimum seconds between vision LLM calls per session. Cost-discipline floor.",
    )
    vision_novelty_threshold: float = Field(default=0.15, ge=0.0, le=1.0,
        description="Perceptual aHash diff threshold above which a frame is flagged as novel.",
    )
    working_memory_capacity: int = Field(default=8, ge=1, le=64,
        description="Per-agent vision working memory ring buffer size.",
    )
    vision_tier: str = Field(default="vision",
        description="LLM tier name for vision describe calls. AD-742a forward marker for vision_fast split.",
    )
===END REPLACE===
```

### Section 5: Wire the consumer into runtime startup

Add to `src/probos/startup/finalize.py` near the engineering sensor block (search for `engineering_sensor_start_task`). The exact insertion site is Builder's call — follow the pattern. Sketch:

```python
# AD-733a (Wave 171): VisionConsumer — bridge vision_observation → working memory.
try:
    _perception_cfg = getattr(runtime.config, "perception", None)
    if _perception_cfg is not None and _perception_cfg.enabled and _perception_cfg.vision_consumer_enabled:
        from probos.perception.consumer import VisionConsumer
        consumer = VisionConsumer(
            runtime,
            min_interval_seconds=_perception_cfg.vision_min_interval_seconds,
            novelty_threshold=_perception_cfg.vision_novelty_threshold,
            working_memory_capacity=_perception_cfg.working_memory_capacity,
            vision_tier=_perception_cfg.vision_tier,
        )
        # Register every crew agent with vision_capable=True as an observer.
        # BF-287: never reach into registry.agents — use the public all() iterator.
        for agent in runtime.registry.all():
            _prof = runtime.callsign_registry.get_profile(getattr(agent, "agent_type", ""))
            if (_prof or {}).get("vision_capable", False):
                consumer.register_observer(agent.id)
        consumer.subscribe()
        runtime.vision_consumer = consumer
        logger.info("AD-733a: VisionConsumer wired with %d observers", len(consumer._observer_agent_ids))
except Exception:
    logger.warning("AD-733a: VisionConsumer wiring failed; vision_observation intents will be silently dropped", exc_info=True)
```

**Builder note.** Pass-2 verified: `AgentRegistry.all()` returns `list[BaseAgent]` (`src/probos/substrate/registry.py:67`). The private `_agents` dict and the cached `_all_cache` are NOT public surface — never reach into them (BF-287). Tests must use a real `AgentRegistry` instance and `await registry.register(agent)`, not MagicMock.

### Section 6: Inject `current_scene` into `agent_chat`'s message_text

`src/probos/routers/agents.py` — extend the existing `targeted_recall_block` prepend pattern (verified ~line 1922).

```
===SEARCH===
    # AD-725 (Wave 159): prepend the targeted recall block so the receiving
    # agent's LLM call sees it as part of the user message.
    if targeted_recall_block is not None:
        message_text = f"{targeted_recall_block}\n\n{message_text}"
===REPLACE===
    # AD-725 (Wave 159): prepend the targeted recall block so the receiving
    # agent's LLM call sees it as part of the user message.
    if targeted_recall_block is not None:
        message_text = f"{targeted_recall_block}\n\n{message_text}"

    # AD-733a (Wave 171): prepend the agent's current visual context.
    # Confabulation guard (BF-294 lesson): render_for_prompt returns a
    # non-empty "no data" sentinel when the buffer is empty, so the agent
    # never silently invents a scene. Tier-2 — failure logs at debug and
    # drops the visual block; the DM still goes through.
    try:
        from probos.perception.consumer import get_or_create_working_memory
        _wm = get_or_create_working_memory(agent_id)
        _scene_block = _wm.render_for_prompt()
        if _scene_block:
            message_text = f"{_scene_block}\n\n{message_text}"
    except Exception:
        logger.debug("AD-733a: scene-context injection failed for %s", agent_id, exc_info=True)
===END REPLACE===
```

### Section 7: Tests — `tests/test_ad733a_vision_consumer.py` (NEW)

Real fixtures, no MagicMock at the substrate boundary (BF-286 / BF-287 lesson).

Required test cases (18 total):

**Supervisor (6):**
1. `test_first_frame_always_allowed` — first frame returns `allow=True, reason="first_frame"`.
2. `test_throttle_blocks_within_interval` — second frame within `min_interval` returns `allow=False, reason="throttled"`.
3. `test_low_novelty_blocked` — identical frame after throttle window returns `allow=False, reason="low_novelty"`.
4. `test_high_novelty_allowed` — different frame after throttle window returns `allow=True, reason="novel"`.
5. `test_corrupt_jpeg_falls_through_to_throttle` — non-JPEG bytes don't raise; throttle still governs.
6. `test_strategy_protocol_pluggable` — fake strategy implementing the Protocol is accepted by VisionSupervisor.

**WorkingMemory (4):**
7. `test_empty_buffer_renders_no_data_sentinel` — confabulation guard string includes "Camera not active or no frames described yet" and "Do NOT describe what you cannot see".
8. `test_render_shows_latest_with_age` — single entry renders age in seconds.
9. `test_ring_buffer_eviction` — capacity=2, append 3 → only last 2 retained.
10. `test_thread_safety` — concurrent append + entries() from 4 threads, no exceptions.

**Consumer (5):**
11. `test_consumer_subscribes_to_vision_observation` — bus subscriber registered under the right intent name.
12. `test_consumer_skips_missing_attachment` — sha not in store → debug log, no LLM call, no episode.
13. `test_supervisor_blocked_frame_skips_llm` — fake supervisor returns `allow=False` → LLM never called.
14. `test_describe_success_writes_to_all_observers` — 2 observers registered, both WMs get the observation.
15. `test_episode_anchor_uses_importance_6` — assert `Episode.importance == 6` and `AnchorFrame.trigger_type == "vision_described"`.

**Integration (3):**
16. `test_dm_reply_prepends_scene_block` — agent_chat with non-empty WM injects the block into message_text before the bus.send.
17. `test_dm_reply_with_empty_wm_injects_no_data_sentinel` — confabulation guard fires when WM empty.
18. `test_vision_consumer_disabled_via_config` — `vision_consumer_enabled=False` → consumer not wired (assert via runtime attribute absent).

Use the `tests/conftest.py` `runtime_fixture` (or build one if absent — check `test_ad733_camera_streaming.py` for the existing pattern). Mock the `llm_client.complete` to return a canned `LLMResponse(content="A glass of water.")` — that's the only mock at a service boundary, NOT a substrate boundary.

---

## What This Does NOT Change

- `routers/perception.py` — wire shape, frame ingestion, rate limiter, anchor episode stay as Wave 170 shipped.
- AD-732 vision tier infrastructure (single `vision` tier reused for v1 — AD-742a is the split).
- AD-731 ref-shape invariant — frame bytes stay in AttachmentStore.
- DmReplyPipeline (post-LLM cleanup) — visual context goes in pre-LLM via message_text prepend, not via the post-LLM pipeline.
- Settings UI — child-disable + status badge is BF-298's job.
- Identity recognition — v1 leaves `subject_identity="unknown"` always; AD-733b populates.

---

## Tracking

- Append to `PROGRESS.md` "Wave 171 — Live Camera Perception" section.
- Append to `docs/development/roadmap.md` Phase 24+ row with closure of #665.
- DECISIONS.md — one paragraph documenting NeuralCompanion absorption attribution + the eight research-question decisions.

---

## Acceptance Criteria

- All 18 new tests pass under `pytest tests/test_ad733a_vision_consumer.py -v -n 0`.
- Full gate: `pytest tests/ -q -n 4 --dist=loadfile` passes — no regression in 1575+ existing tests.
- AD-731 source-scan test still passes: no `b64encode`, no `base64.b64` in `perception/consumer.py` or `perception/supervisor.py`.
- Manual smoke (Captain test step 1-4 from dispatch doc): enable camera → hold up object → describe in DM. The agent's reply references the object.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

| Claim | Verification |
|---|---|
| `IntentBus.subscribe(agent_id, handler, intent_names=[...])` | `src/probos/mesh/intent.py:115` |
| `runtime.intent_bus.broadcast` for vision_observation | `src/probos/routers/perception.py:139` |
| `IntentMessage(intent="vision_observation", params={"attachment_ref": sha, ...})` | `src/probos/routers/perception.py:131-140` |
| AttachmentStore reachable via `_get_attachment_store(runtime)` | `src/probos/routers/agents.py:1726` |
| `LLMRequest(messages=..., tier=..., max_tokens=..., prompt="")` shape | `src/probos/types.py:227-245` (`messages` field added AD-720d) |
| `build_multimodal_messages(prompt, attachment_ids, store, mime_lookup, text_extraction_max_bytes, pdf_extraction_enabled)` | `src/probos/cognitive/vision_dispatch.py:158` |
| `Episode(timestamp, user_input, outcomes, reflection, source, importance, anchors)` shape | `src/probos/routers/perception.py:73-91` (AD-733 v1 anchor) |
| `AnchorFrame(channel, trigger_type, trigger_agent)` shape | same — `src/probos/routers/perception.py:86-89` |
| `targeted_recall_block` prepend pattern in agent_chat | `src/probos/routers/agents.py:1922-1925` |
| `PerceptionConfig` location | `src/probos/config.py:1920` |
| `runtime.config.perception.enabled` access pattern | `src/probos/routers/perception.py:97-101` |
| `runtime.callsign_registry.get_profile(agent_type)` returning dict with `vision_capable` | `src/probos/routers/agents.py:1801-1810` |
| `runtime.llm_client.complete(LLMRequest, ...)` returns `LLMResponse` with `content` | `src/probos/cognitive/llm_client.py:45, 490` |
| `episodic_memory.store(Episode)` is async | `src/probos/routers/perception.py:91` |
| `_LLM_TIERS` includes "vision" (AD-732) | searched — AD-732 / BF-273 documented in user memory; vision tier operational |
