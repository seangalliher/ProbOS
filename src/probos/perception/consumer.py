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

# AD-742f: optional shared store wired at runtime startup. None = legacy
# in-memory-only behavior (BF-274 fallback path).
_WM_STORE: Any = None


def set_working_memory_store(store: Any) -> None:
    """AD-742f: install the shared SQLite store. None disables persistence."""
    global _WM_STORE
    _WM_STORE = store


def get_or_create_working_memory(agent_id: str, *, capacity: int = 8) -> Any:
    """Return the VisionWorkingMemory for an agent, creating on first access."""
    from probos.perception.working_memory import VisionWorkingMemory
    if agent_id not in _WORKING_MEMORIES:
        _WORKING_MEMORIES[agent_id] = VisionWorkingMemory(
            capacity=capacity,
            store=_WM_STORE,
            agent_id=agent_id,
        )
    return _WORKING_MEMORIES[agent_id]


def reset_working_memories_for_tests() -> None:
    """Test-only — clears the module-level WM registry AND the store handle."""
    global _WM_STORE
    _WORKING_MEMORIES.clear()
    _WM_STORE = None


def _reset_latest_frame_cache_for_tests(consumer: Any) -> None:
    """AD-733c-1 test helper — clears per-consumer latest-frame caches."""
    consumer._latest_frame_by_session.clear()
    consumer._latest_frame_global = None


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
        baseline_max_age_seconds: float = 30.0,
        working_memory_capacity: int = 8,
        vision_tier: str = "vision",
        vision_fast_tier: str = "vision_fast",
        max_describe_tokens: int = 220,
        describe_timeout_s: float = 30.0,
        supervisor_strategy_name: str = "ahash",
    ) -> None:
        from probos.perception.supervisor import VisionSupervisor, build_strategy

        self._runtime = runtime
        self._strategy_name = str(supervisor_strategy_name)
        self._supervisor = VisionSupervisor(
            strategy=build_strategy(
                self._strategy_name,
                min_interval_seconds=min_interval_seconds,
                novelty_threshold=novelty_threshold,
                baseline_max_age_seconds=baseline_max_age_seconds,
            )
        )
        self._wm_capacity = working_memory_capacity
        self._tier = vision_tier
        self._fast_tier = vision_fast_tier
        self._max_tokens = max_describe_tokens
        self._timeout = describe_timeout_s
        # BF-304: single-flight guard around the vision LLM call. Vision
        # tier inference is heavy (qwen3.6:27b on local Ollama / OpenAI
        # vision endpoint); allowing multiple concurrent describe() calls
        # blew RAM/VRAM and crashed the process with a Rust alloc failure.
        # The right semantic for a frame stream is "best snapshot, not a
        # queue" — frames arriving while a describe is in flight are
        # dropped with an INFO log. The next supervisor-allowed (or forced)
        # frame picks up where the dropped one left off.
        import asyncio as _asyncio
        from collections import deque as _deque
        self._describe_lock = _asyncio.Lock()
        # BF-306: ring buffer of recent supervisor / consumer decisions so the
        # operator preview can show WHY frames are being dropped. Each entry:
        # (timestamp, reason, sha_prefix, novelty_score). Capped at 32.
        self._recent_decisions: _deque[tuple[float, str, str, float]] = _deque(maxlen=32)
        # Set of agent_ids that should receive observations. For v1 this
        # is "every crew agent with vision_capable=True". The consumer
        # writes to each such agent's WorkingMemory on every flagged frame.
        self._observer_agent_ids: set[str] = set()
        # AD-733b: identity-resolution + proactive-observer state. The hooks
        # are no-ops when the observer is not wired or the captain reference
        # avatar is empty — the AD-733a code path stays intact.
        self._identity_resolved_sessions: set[str] = set()
        # AD-742b: lazy-constructed face-embedding resolver. Threaded
        # through __init__ rather than constructed here so tests can
        # inject a stub.
        self._identity_resolver: Any = None

        # AD-742e (Wave 174): per-tier vision LLM call counters. Reset
        # per-session on session change; per-day on UTC date rollover.
        # v1 in-memory only — AD-742e-1 forward marker for SQLite
        # persistence across restart.
        self._budget_calls_session: dict[str, int] = {"vision": 0, "vision_fast": 0}
        self._budget_calls_today: dict[str, int] = {"vision": 0, "vision_fast": 0}
        self._budget_current_session_id: str = ""
        self._budget_current_date: str = ""  # YYYY-MM-DD UTC
        self._budget_last_call_at: float | None = None
        self._sessions_with_observations: set[str] = set()
        self._observer: Any = None
        # AD-733c-1: per-session latest-frame SHA cache. Updated in
        # ``_handle`` BEFORE supervisor admission so dropped/throttled frames
        # still register. Used by ``force_describe_current_frame`` to fetch
        # the most recent visible frame on a DM-receive hook. Each value is
        # ``(sha, captured_at)``. Module-scoped per-runtime; cleared in
        # ``reset_working_memories_for_tests``.
        self._latest_frame_by_session: dict[str, tuple[str, float]] = {}
        self._latest_frame_global: tuple[str, float] | None = None

    @property
    def observer_agent_ids(self) -> set[str]:
        """Public view for tests + diagnostics; copy on read."""
        return set(self._observer_agent_ids)

    def register_observer(self, agent_id: str) -> None:
        self._observer_agent_ids.add(agent_id)

    def recent_decisions(self, limit: int = 16) -> list[dict[str, Any]]:
        """BF-306: return the most recent supervisor / consumer decisions for
        the operator preview panel. Newest first. Each entry: timestamp +
        reason ('first_frame'|'novel'|'low_novelty'|'throttled'|'forced'|'busy')
        + sha prefix + novelty score in [0, 1].
        """
        items = list(self._recent_decisions)
        items.reverse()
        capped = items[: max(1, min(limit, 32))]
        return [
            {"timestamp": ts, "reason": reason, "sha": sha, "novelty_score": novelty}
            for (ts, reason, sha, novelty) in capped
        ]

    def wire_proactive_observer(self, observer: Any) -> None:
        """AD-733b: attach the ProactiveVisionObserver. Idempotent."""
        self._observer = observer

    def subscribe(self) -> None:
        """Register on the intent bus. Idempotent at the bus level."""
        self._runtime.intent_bus.subscribe(
            self.SUBSCRIBER_AGENT_ID,
            self._handle,
            intent_names=[self.INTENT_NAME],
        )
        logger.info("AD-733a: VisionConsumer subscribed to %s", self.INTENT_NAME)

    def set_identity_resolver(self, resolver: Any) -> None:
        """AD-742b: hot-swap the IdentityResolver. None disables resolution."""
        self._identity_resolver = resolver

    def _record_vision_call(self, tier: str, session_id: str) -> None:
        """AD-742e: record one vision LLM call against the budget counters."""
        import time as _time
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if session_id != self._budget_current_session_id:
            self._budget_current_session_id = session_id
            self._budget_calls_session = {"vision": 0, "vision_fast": 0}
        if today != self._budget_current_date:
            self._budget_current_date = today
            self._budget_calls_today = {"vision": 0, "vision_fast": 0}
        if tier not in self._budget_calls_session:
            self._budget_calls_session[tier] = 0
            self._budget_calls_today[tier] = 0
        self._budget_calls_session[tier] += 1
        self._budget_calls_today[tier] += 1
        self._budget_last_call_at = _time.monotonic()

    def get_budget_snapshot(self) -> dict[str, Any]:
        """AD-742e: structured snapshot for /api/perception/budget."""
        import time as _time
        next_allowed_in: float = 0.0
        if self._budget_last_call_at is not None:
            # Heuristic: use the configured vision_min_interval_seconds floor
            # as a proxy for "when's the next describe likely allowed?" — the
            # supervisor enforces the actual cadence; this is informational.
            cfg_perception = getattr(self._runtime.config, "perception", None)
            min_interval = (
                float(getattr(cfg_perception, "vision_min_interval_seconds", 3.0))
                if cfg_perception is not None
                else 3.0
            )
            elapsed = _time.monotonic() - self._budget_last_call_at
            next_allowed_in = max(0.0, min_interval - elapsed)
        ceiling = 0
        # session ceiling = proactive_max_emissions * 40 (heuristic — actual
        # ceiling is a function of session duration which isn't known here).
        cfg = getattr(self._runtime.config, "perception", None)
        if cfg is not None:
            ceiling = int(getattr(cfg, "proactive_max_emissions", 3)) * 40
        return {
            "session_id": self._budget_current_session_id,
            "calls_this_session": dict(self._budget_calls_session),
            "calls_today": dict(self._budget_calls_today),
            "total_session": sum(self._budget_calls_session.values()),
            "total_today": sum(self._budget_calls_today.values()),
            "session_ceiling_estimate": ceiling,
            "next_allowed_in_seconds": round(next_allowed_in, 2),
        }

    async def _handle(self, msg: IntentMessage) -> IntentResult | None:
        """Bus handler — supervisor-gate, LLM-describe, WM-write, episode-anchor."""
        if msg.intent != self.INTENT_NAME:
            return None
        # AD-733c-1: record the SHA BEFORE supervisor gating so force-describe
        # can fetch it even when the supervisor dropped this frame for
        # low-novelty / throttled reasons.
        try:
            _sha = msg.params.get("attachment_ref")
            _captured_at = float(msg.params.get("captured_at", time.time()))
            _session_id = str(msg.params.get("session_id", ""))
            if isinstance(_sha, str) and _sha:
                if _session_id:
                    self._latest_frame_by_session[_session_id] = (_sha, _captured_at)
                self._latest_frame_global = (_sha, _captured_at)
        except Exception:
            logger.debug("AD-733c-1: latest-frame cache update failed", exc_info=True)
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

        # 2) Supervisor gate. BF-302: ``force=True`` in intent params bypasses
        # the supervisor entirely — operator-driven preview / debug path.
        # BF-303: novelty_score must be defined for BOTH branches because the
        # downstream VisionObservation + anchor episode reference it.
        is_forced = bool(msg.params.get("force", False))
        if is_forced:
            logger.info("AD-733a: forced describe sha=%s (supervisor bypassed)", sha[:8])
            novelty_score = 1.0  # forced frames are "maximally novel" by operator decree
            self._recent_decisions.append((time.time(), "forced", sha[:8], 1.0))
        else:
            decision = self._supervisor.admit(frame_bytes)
            self._recent_decisions.append(
                (time.time(), decision.reason, sha[:8], decision.novelty_score)
            )
            if not decision.allow:
                # BF-306: bumped debug -> info so operator can see drop reasons
                # without enabling debug logging across the whole runtime.
                logger.info(
                    "AD-733a: supervisor dropped frame sha=%s reason=%s novelty=%.2f",
                    sha[:8], decision.reason, decision.novelty_score,
                )
                return
            novelty_score = decision.novelty_score

        # 3) Vision LLM describe. BF-304: single-flight — if a describe is
        # already running, drop this frame rather than pile up concurrent
        # heavy vision-tier calls. The 5s supervisor throttle normally
        # prevents this; the lock catches force-spam + first-window bursts
        # that bypass the throttle.
        if self._describe_lock.locked():
            logger.info(
                "AD-733a: dropping frame sha=%s (describe already in flight; "
                "single-flight per BF-304)",
                sha[:8],
            )
            self._recent_decisions.append((time.time(), "busy", sha[:8], novelty_score))
            return
        async with self._describe_lock:
            # AD-742e: thread the current session_id into the consumer so the
            # budget counter's reset-on-session-change logic sees the right
            # bucket. Effective default when callers don't set session_id.
            if session_id:
                self._budget_current_session_id = session_id
            description = await self._describe(sha)
        if not description:
            logger.info("AD-733a: vision LLM returned empty for sha=%s", sha[:8])
            return

        # 4) Write to every registered observer's WorkingMemory.
        from probos.perception.working_memory import VisionObservation

        # AD-733b: identity hook — once per session, ask the vision LLM
        # whether the person in frame matches the Captain reference avatar.
        # Skipped when no reference image is available; identity stays "unknown".
        subject_identity = "unknown"
        if session_id and session_id not in self._identity_resolved_sessions:
            subject_identity = await self._resolve_subject_identity(sha)
            self._identity_resolved_sessions.add(session_id)

        obs = VisionObservation(
            timestamp=time.time(),
            attachment_ref=sha,
            description=description[:400],
            novelty_score=novelty_score,
            subject_identity=subject_identity,
            session_id=session_id,
        )
        for agent_id in list(self._observer_agent_ids):
            wm = get_or_create_working_memory(agent_id, capacity=self._wm_capacity)
            wm.append(obs)

        # 5) Anchor an episode (AD-541b — importance=6, lower than camera_began=8).
        # BF-311: tag with the observer agent_ids so per-agent episodic recall
        # can surface these episodes. Without this, ``agent_ids_json = []``
        # and the episodes are invisible to every agent's recall query —
        # they exist in chroma but aren't retrievable, which silently breaks
        # the AD-541b promise that perception observations form long-term memory.
        anchor_agent_ids = list(self._observer_agent_ids)
        await self._anchor_episode(
            sha, description, novelty_score, session_id,
            agent_ids=anchor_agent_ids,
        )

        # 6) AD-733b: proactive observer — may emit one DM per observer if
        # the scene-introduction or high-novelty trigger fires. Tier-2:
        # never blocks subsequent frames. The "first observation in session"
        # signal is tracked here; per-agent emission accounting lives inside
        # the observer.
        if self._observer is not None and session_id:
            first_for_session = session_id not in self._sessions_with_observations
            if first_for_session:
                self._sessions_with_observations.add(session_id)
            for agent_id in list(self._observer_agent_ids):
                try:
                    await self._observer.maybe_emit(
                        session_id=session_id,
                        agent_id=agent_id,
                        observation=obs,
                        is_first_observation=first_for_session,
                    )
                except Exception:
                    logger.debug(
                        "AD-733b: observer.maybe_emit raised for agent=%s",
                        agent_id, exc_info=True,
                    )

    async def force_describe_current_frame(
        self,
        session_id: str | None = None,
        *,
        timeout_s: float = 4.0,
    ) -> str | None:
        """AD-733c-1: synchronously describe the latest cached frame.

        Looks up the most recent frame SHA for ``session_id`` (or globally
        if no session given), runs the standard ``_process`` path with
        ``force=True`` (bypasses the supervisor), and returns the
        description as written to working memory. Tier-2 honest-degrade:
        on timeout / no cached frame / LLM error, returns ``None`` and
        logs at WARNING (not ERROR — the DM still proceeds without the
        fresh frame).

        ``timeout_s`` is a hard wall-clock cap: the caller (DM hook) must
        not block on a slow vision tier. BF-304 single-flight lock means
        spamming this call collapses to one describe per supervisor
        window.
        """
        if session_id and session_id in self._latest_frame_by_session:
            sha, captured_at = self._latest_frame_by_session[session_id]
        elif self._latest_frame_global is not None:
            sha, captured_at = self._latest_frame_global
        else:
            logger.debug(
                "AD-733c-1: force_describe — no cached frame for session=%s",
                str(session_id or "*")[:8],
            )
            return None
        synthetic = IntentMessage(
            intent=self.INTENT_NAME,
            params={
                "attachment_ref": sha,
                "mime": "image/jpeg",
                "captured_at": captured_at,
                "source": "force_describe",
                "session_id": session_id or "",
                "force": True,
            },
        )
        try:
            await asyncio.wait_for(self._process(synthetic), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "AD-733c-1: force_describe timed out after %.1fs sha=%s",
                timeout_s, sha[:8],
            )
            return None
        except Exception:
            logger.warning(
                "AD-733c-1: force_describe raised for sha=%s; DM proceeds without fresh frame",
                sha[:8], exc_info=True,
            )
            return None
        # Pull the just-written description out of any observer's WM.
        # The describe path wrote the same VisionObservation to every
        # observer's WM, so the first observer's most-recent entry is the
        # description we just produced.
        for agent_id in list(self._observer_agent_ids):
            wm = get_or_create_working_memory(agent_id, capacity=self._wm_capacity)
            entries = list(wm.entries())
            if entries and entries[-1].attachment_ref == sha:
                return entries[-1].description
        return None

    async def _describe(self, sha: str) -> str:
        """Call the vision LLM on a single frame. Returns description or empty string."""
        try:
            from probos.cognitive.vision_dispatch import build_multimodal_messages
            from probos.routers.chat import _get_attachment_store
            store = _get_attachment_store(self._runtime)

            async def _mime_lookup(content_hash: str) -> str | None:
                return await store.mime_for(content_hash)

            # AD-742a: route per-frame describes to vision_fast when
            # configured. The LLMClient's fallback chain (llm_client.py:557)
            # automatically routes vision_fast -> vision when fast is
            # unconfigured / unhealthy. NO text-tier fallback (BF-269).
            from probos.cognitive.vision_dispatch import is_vision_tier_configured
            cog_cfg = getattr(self._runtime.config, "cognitive", None)
            describe_tier = self._fast_tier if (
                cog_cfg is not None
                and is_vision_tier_configured(cog_cfg, self._fast_tier)
            ) else self._tier

            # BF-314: per-tier prompt + sampling. moondream (1.8B) loops on
            # multi-clause prompts and emits hallucinated numbered lists
            # ("1. The cat is black and white. 2. The cat is black and
            # white." with no cat in frame). It needs a single direct
            # question + temperature 0 + tight token cap. qwen3.6:27b
            # handles complex structured prompts fine, keep the original.
            if describe_tier == self._fast_tier:
                prompt = (
                    "Describe what is in this image in one or two sentences. "
                    "Include any person and what they are wearing. "
                    "Do not invent details."
                )
                temperature = 0.0
                max_tokens = 80
            else:
                prompt = (
                    "Briefly describe what you see in this frame. "
                    "If a person is visible, describe their clothing and what they're doing. "
                    "If they are holding an object, name and describe the object. "
                    "Keep the description under 80 words. Do not speculate beyond what is visible."
                )
                temperature = 0.2
                max_tokens = self._max_tokens

            messages, image_ids, _per = await build_multimodal_messages(
                prompt=prompt,
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
                tier=describe_tier,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            # AD-742e: record successful call against the budget counter.
            # `describe_tier` is the resolved tier (vision_fast when configured,
            # else vision) from the AD-742a routing block above.
            self._record_vision_call(describe_tier, self._budget_current_session_id or "default")
            return (response.content or "").strip()
        except Exception:
            logger.warning(
                "AD-733a: vision LLM describe failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return ""

    async def _resolve_subject_identity(self, sha: str) -> str:
        """AD-742b: face-embedding identity check (replaces AD-733b LLM prompt).

        Returns 'captain' | 'unknown' | 'other'. Falls back to the AD-733b
        LLM-prompt path only when ``identity_resolver_enabled=False`` AND a
        ``captain_avatar_ref`` is set. Default path: cheap, local, no LLM call.
        """
        # AD-742b: face-embedding path (default).
        resolver = self._identity_resolver
        if resolver is not None and resolver.is_enrolled():
            try:
                from probos.routers.chat import _get_attachment_store
                store = _get_attachment_store(self._runtime)
                live_bytes = await store.read(sha)
                if not live_bytes:
                    return "unknown"
                # MTCNN/Resnet are sync + CPU-bound; offload from the loop.
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, resolver.resolve, live_bytes)
            except Exception:
                logger.debug(
                    "AD-742b: face-embedding resolve failed for sha=%s",
                    sha[:8], exc_info=True,
                )
                return "unknown"

        # AD-733b legacy path: only when resolver disabled AND legacy ref set.
        try:
            captain_avatar_sha = self._lookup_captain_avatar_ref()
            if not captain_avatar_sha:
                return "unknown"

            from probos.cognitive.vision_dispatch import build_multimodal_messages
            from probos.routers.chat import _get_attachment_store
            store = _get_attachment_store(self._runtime)

            async def _mime_lookup(content_hash: str) -> str | None:
                return await store.mime_for(content_hash)

            messages, image_ids, _ = await build_multimodal_messages(
                prompt=(
                    "Two images follow. The first is a reference photo of the operator "
                    "(the Captain). The second is a live camera frame. Reply with EXACTLY "
                    "one word, lowercase: 'captain' if the live frame contains the operator, "
                    "'other' if it contains a different person, 'unknown' if no person is "
                    "clearly visible or the comparison is ambiguous."
                ),
                attachment_ids=[captain_avatar_sha, sha],
                store=store,
                mime_lookup=_mime_lookup,
                text_extraction_max_bytes=0,
                pdf_extraction_enabled=False,
            )
            if len(image_ids) < 2:
                return "unknown"

            request = LLMRequest(
                prompt="",
                messages=messages,
                tier=self._tier,
                max_tokens=8,
                temperature=0.0,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            word_list = (response.content or "").strip().lower().split()
            if word_list and word_list[0] in ("captain", "other", "unknown"):
                return word_list[0]
            return "unknown"
        except Exception:
            logger.debug(
                "AD-733b: identity resolve failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return "unknown"

    def _lookup_captain_avatar_ref(self) -> str | None:
        """AD-733b: best-effort lookup of the Captain's reference avatar SHA.

        v1 strategy: ``runtime.config.perception.captain_avatar_ref``. AD-742b
        will replace this with proper face-embedding enrollment.
        """
        cfg = getattr(self._runtime.config, "perception", None)
        if cfg is None:
            return None
        ref = getattr(cfg, "captain_avatar_ref", "")
        return ref if isinstance(ref, str) and ref else None

    async def _anchor_episode(
        self, sha: str, description: str, novelty: float, session_id: str,
        *, agent_ids: list[str] | None = None,
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
                # BF-311: tag with observer agent_ids so per-agent recall can
                # surface these episodes. Falls back to empty list (legacy
                # behavior) if caller doesn't supply one.
                agent_ids=list(agent_ids) if agent_ids else [],
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
