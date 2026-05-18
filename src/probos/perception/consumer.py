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
_WORKING_MEMORIES: dict[str, Any] = {}  # agent_id -> VisionWorkingMemory


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
    """Runtime-owned consumer that bridges vision_observation -> working memory."""

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

    @property
    def observer_agent_ids(self) -> set[str]:
        """Public view for tests + diagnostics; copy on read."""
        return set(self._observer_agent_ids)

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
                str(msg.params.get("session_id", ""))[:8],
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
        try:
            frame_bytes = await store.read(sha)
        except Exception:
            logger.warning(
                "AD-733a: AttachmentStore.read failed sha=%s; skipping frame",
                sha[:8], exc_info=True,
            )
            return
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
            logger.warning(
                "AD-733a: vision LLM describe failed for sha=%s",
                sha[:8], exc_info=True,
            )
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


__all__ = [
    "VisionConsumer",
    "get_or_create_working_memory",
    "reset_working_memories_for_tests",
]
