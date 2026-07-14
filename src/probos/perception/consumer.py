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
import math
import time
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, AsyncIterator

from probos.perception.working_memory import VisionObservation
from probos.types import (
    AnchorFrame,
    Episode,
    IntentMessage,
    IntentResult,
    LLMRequest,
)

logger = logging.getLogger(__name__)


_LatestFrameCandidate = tuple[str, float]


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
    with consumer._latest_frame_lock:
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
        # AD-733c-6: per-session set so the cap-hit WARNING + WardRoom-class
        # log fires once per session, not once per ENGAGED call past the cap.
        self._budget_cap_notified_sessions: set[str] = set()
        self._sessions_with_observations: set[str] = set()
        self._observer: Any = None
        # AD-733c-1: per-session latest-frame SHA cache. Updated in
        # ``_handle`` BEFORE supervisor admission so dropped/throttled frames
        # still register. Used by ``force_describe_current_frame`` to fetch
        # the most recent visible frame on a DM-receive hook. Each value is
        # ``(sha, captured_at)``. BF-666: one synchronous lock owns snapshots,
        # monotonic writes, and compare-clears; the separate async force lock
        # collapses concurrent public force calls before storage selection.
        self._latest_frame_lock = Lock()
        self._force_describe_lock = asyncio.Lock()
        self._latest_frame_by_session: dict[str, _LatestFrameCandidate] = {}
        self._latest_frame_global: _LatestFrameCandidate | None = None
        # BF-617: the most-recent VisionObservation produced by ``_process``,
        # regardless of which observers it fanned out to. A shared-camera
        # meeting has ONE feed; a present crew member who is not a registered
        # ambient observer (vision_capable=False, e.g. the yeoman) still needs
        # to see it. ``_render_agent_scene_block`` falls back to this shared
        # observation when an agent's own ring is empty, so everyone in the room
        # sees the one camera without enrolling them in ambient perception.
        self._last_observation: Any = None

    @property
    def observer_agent_ids(self) -> set[str]:
        """Public view for tests + diagnostics; copy on read."""
        return set(self._observer_agent_ids)

    def latest_shared_observation(self) -> Any:
        """BF-617: the most-recent VisionObservation to share into a present
        participant's empty ring, or ``None``.

        The shared-camera view for a meeting: any present participant whose own
        working-memory ring is empty (not a registered ambient observer, e.g.
        the yeoman) renders this so they see the same feed everyone else does.

        BF-620: ``_last_observation`` is in-RAM and starts ``None`` after a
        restart, but a registered observer's ring may already hold the feed —
        either hydrated from disk (AD-742f persistence) or written by an earlier
        describe this session. Relying on ``_last_observation`` alone meant that
        right after a restart a vision-capable observer (ring hydrated) could see
        while a non-observer's fallback found ``None`` and rendered the "camera
        not active" sentinel — the exact "Yeo can't see but Ezri can" report.
        So when ``_last_observation`` is unset, borrow the most-recent
        observation any registered observer currently holds. Read-only.
        """
        if self._last_observation is not None:
            return self._last_observation
        latest: Any = None
        for _aid in self._observer_agent_ids:
            try:
                _wm = get_or_create_working_memory(_aid, capacity=self._wm_capacity)
                _obs = _wm.latest()
            except Exception:
                logger.debug(
                    "BF-620: observer-ring scan failed for %s", _aid, exc_info=True
                )
                continue
            if _obs is not None and (
                latest is None or _obs.timestamp > latest.timestamp
            ):
                latest = _obs
        return latest

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
        """AD-742e: record one vision LLM call. AD-733c-6: enforce cap."""
        import time as _time
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if session_id != self._budget_current_session_id:
            self._budget_current_session_id = session_id
            self._budget_calls_session = {"vision": 0, "vision_fast": 0}
            # AD-733c-6: clear the "we've already notified" flag so the
            # cap-hit log fires once per session, not once per process.
            self._budget_cap_notified_sessions.discard(session_id)
        if today != self._budget_current_date:
            self._budget_current_date = today
            self._budget_calls_today = {"vision": 0, "vision_fast": 0}
        if tier not in self._budget_calls_session:
            self._budget_calls_session[tier] = 0
            self._budget_calls_today[tier] = 0
        self._budget_calls_session[tier] += 1
        self._budget_calls_today[tier] += 1
        self._budget_last_call_at = _time.monotonic()
        # AD-733c-6: cap-check + auto-drop. Defense-in-depth: if any piece
        # of the path is missing (config, controller), silently skip — the
        # counters still work (AD-742e behavior preserved).
        self._maybe_enforce_budget(session_id)

    def _maybe_enforce_budget(self, session_id: str) -> None:
        """AD-733c-6: drop to AMBIENT when cap exceeded in ENGAGED mode."""
        cfg = getattr(getattr(self._runtime, "config", None), "perception", None)
        if cfg is None or not getattr(cfg, "engaged_budget_enforcement", True):
            return
        controller = getattr(self._runtime, "perception_mode_controller", None)
        if controller is None:
            return
        # Late-import the enum so module-load order doesn't trip us.
        from probos.perception.mode_controller import Mode as _Mode
        if controller.current_mode is not _Mode.ENGAGED:
            return
        cap_session = int(getattr(cfg, "engaged_call_cap_per_session", 200))
        cap_day = int(getattr(cfg, "engaged_call_cap_per_day", 2000))
        total_session = sum(self._budget_calls_session.values())
        total_today = sum(self._budget_calls_today.values())
        if total_session < cap_session and total_today < cap_day:
            return
        # Cap hit. Transition synchronously (mode_controller.transition_to
        # is sync; safe to call while holding describe_lock — no async
        # acquisition, no re-entry).
        reason = "session" if total_session >= cap_session else "day"
        try:
            controller.transition_to(_Mode.AMBIENT, trigger="budget_exhausted")
        except Exception:
            logger.warning(
                "AD-733c-6: budget-exhausted transition failed (cap=%s)",
                reason, exc_info=True,
            )
            return
        # Rate-limited operator-visible notification — once per session.
        if session_id and session_id not in self._budget_cap_notified_sessions:
            self._budget_cap_notified_sessions.add(session_id)
            logger.warning(
                "AD-733c-6: vision LLM %s cap reached (session=%d/%d, "
                "day=%d/%d); ENGAGED -> AMBIENT auto-drop",
                reason,
                total_session, cap_session,
                total_today, cap_day,
            )

    def get_budget_snapshot(self) -> dict[str, Any]:
        """AD-742e + AD-733c-6: snapshot for /api/perception/budget."""
        import time as _time
        next_allowed_in: float = 0.0
        cfg = getattr(getattr(self._runtime, "config", None), "perception", None)
        if self._budget_last_call_at is not None:
            min_interval = (
                float(getattr(cfg, "vision_min_interval_seconds", 3.0))
                if cfg is not None
                else 3.0
            )
            elapsed = _time.monotonic() - self._budget_last_call_at
            next_allowed_in = max(0.0, min_interval - elapsed)
        # AD-733c-6: configured caps (replace AD-742e heuristic ceiling).
        cap_session = int(getattr(cfg, "engaged_call_cap_per_session", 200)) if cfg else 200
        cap_day = int(getattr(cfg, "engaged_call_cap_per_day", 2000)) if cfg else 2000
        enforcement = bool(getattr(cfg, "engaged_budget_enforcement", True)) if cfg else True
        # Backwards-compat: keep session_ceiling_estimate for any caller
        # that hasn't migrated to the new cap field. Map to cap_session.
        ceiling = cap_session
        total_session = sum(self._budget_calls_session.values())
        total_today = sum(self._budget_calls_today.values())
        return {
            "session_id": self._budget_current_session_id,
            "calls_this_session": dict(self._budget_calls_session),
            "calls_today": dict(self._budget_calls_today),
            "total_session": total_session,
            "total_today": total_today,
            "session_ceiling_estimate": ceiling,  # AD-742e backcompat
            "cap_per_session": cap_session,
            "cap_per_day": cap_day,
            "enforcement_enabled": enforcement,
            "cap_reached_session": total_session >= cap_session,
            "cap_reached_day": total_today >= cap_day,
            "next_allowed_in_seconds": round(next_allowed_in, 2),
        }

    def _record_latest_frame(
        self,
        sha: str,
        session_id: str,
        captured_at: float,
    ) -> _LatestFrameCandidate | None:
        """Record one finite frame candidate without regressing newer slots."""
        if not isinstance(sha, str) or not sha:
            return None
        try:
            normalized_captured_at = float(captured_at)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(normalized_captured_at):
            return None
        candidate: _LatestFrameCandidate = (sha, normalized_captured_at)
        with self._latest_frame_lock:
            if session_id:
                current_session = self._latest_frame_by_session.get(session_id)
                if (
                    current_session is None
                    or normalized_captured_at >= current_session[1]
                ):
                    self._latest_frame_by_session[session_id] = candidate
            current_global = self._latest_frame_global
            if (
                current_global is None
                or normalized_captured_at >= current_global[1]
            ):
                self._latest_frame_global = candidate
        return candidate

    def _select_latest_frame(
        self,
        session_id: str | None,
    ) -> _LatestFrameCandidate | None:
        """Snapshot the requested session candidate, falling back globally."""
        with self._latest_frame_lock:
            if session_id:
                session_candidate = self._latest_frame_by_session.get(session_id)
                if session_candidate is not None:
                    return session_candidate
            return self._latest_frame_global

    def _clear_latest_frame_if_matches(
        self,
        candidate: _LatestFrameCandidate,
    ) -> int:
        """Atomically clear every session/global alias equal to ``candidate``."""
        removed = 0
        with self._latest_frame_lock:
            matching_sessions = [
                session_id
                for session_id, current in self._latest_frame_by_session.items()
                if current == candidate
            ]
            for session_id in matching_sessions:
                del self._latest_frame_by_session[session_id]
                removed += 1
            if self._latest_frame_global == candidate:
                self._latest_frame_global = None
                removed += 1
        return removed

    def _force_describe_max_age_seconds(self) -> float:
        """Return the configured freshness bound capped by frame retention."""
        cfg = getattr(getattr(self._runtime, "config", None), "perception", None)
        try:
            retention = float(getattr(cfg, "frame_retention_seconds", 300.0))
        except (TypeError, ValueError, OverflowError):
            retention = 300.0
        if not math.isfinite(retention) or retention <= 0.0:
            retention = 300.0
        try:
            freshness = float(getattr(cfg, "prompt_freshness_seconds", 120.0))
        except (TypeError, ValueError, OverflowError):
            freshness = 120.0
        if not math.isfinite(freshness):
            freshness = 120.0
        if freshness <= 0.0:
            return retention
        return min(retention, freshness)

    @asynccontextmanager
    async def _force_describe_permit(self) -> AsyncIterator[bool]:
        """Admit one force call without queuing peers behind its full work."""
        acquired = False
        try:
            try:
                await asyncio.wait_for(
                    self._force_describe_lock.acquire(), timeout=0.001,
                )
            except asyncio.TimeoutError:
                yield False
                return
            acquired = True
            yield True
        finally:
            if acquired:
                self._force_describe_lock.release()

    async def _handle(self, msg: IntentMessage) -> IntentResult | None:
        """Bus handler — supervisor-gate, LLM-describe, WM-write, episode-anchor."""
        if msg.intent != self.INTENT_NAME:
            return None
        # AD-733c-1: record the SHA BEFORE supervisor gating so force-describe
        # can fetch it even when the supervisor dropped this frame for
        # low-novelty / throttled reasons.
        cache_candidate: _LatestFrameCandidate | None = None
        try:
            _sha = msg.params.get("attachment_ref")
            _captured_at = (
                float(msg.params["captured_at"])
                if "captured_at" in msg.params
                else time.time()
            )
            _session_id = str(msg.params.get("session_id", ""))
            cache_candidate = self._record_latest_frame(
                _sha, _session_id, _captured_at,
            )
        except Exception:
            logger.debug("AD-733c-1: latest-frame cache update failed", exc_info=True)
        try:
            await self._process(msg, cache_candidate=cache_candidate)
        except asyncio.CancelledError:
            raise
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

    async def _process(
        self,
        msg: IntentMessage,
        *,
        cache_candidate: _LatestFrameCandidate | None = None,
    ) -> VisionObservation | None:
        # AD-746 Layer 1: a fused message carries multiple refs +
        # parallel sources lists. Use the primary (first) ref for the
        # supervisor + describe path; the full sources list flows into
        # WM metadata + anchor outcomes so per-agent ``bound_sources``
        # filtering and AD-541b semantics see both halves.
        refs_raw = msg.params.get("attachment_refs")
        if isinstance(refs_raw, (list, tuple)) and refs_raw:
            attachment_refs: list[str] = [
                str(r) for r in refs_raw if isinstance(r, str) and r
            ]
        else:
            single = msg.params.get("attachment_ref")
            attachment_refs = [single] if isinstance(single, str) and single else []
        sources_raw = msg.params.get("sources")
        if isinstance(sources_raw, (list, tuple)) and sources_raw:
            sources_list: list[str] = [
                str(s) for s in sources_raw if isinstance(s, str) and s
            ]
        else:
            single_src = str(msg.params.get("source", "camera") or "camera")
            sources_list = [single_src]
        sha = attachment_refs[0] if attachment_refs else None
        session_id = str(msg.params.get("session_id", ""))
        if not sha or not isinstance(sha, str):
            logger.debug("AD-733a: vision_observation missing attachment_ref; skipping")
            return None

        read_candidate = cache_candidate
        if read_candidate is None and "captured_at" in msg.params:
            try:
                explicit_captured_at = float(msg.params["captured_at"])
            except (TypeError, ValueError, OverflowError):
                explicit_captured_at = math.nan
            if math.isfinite(explicit_captured_at):
                read_candidate = (sha, explicit_captured_at)

        # 1) Load bytes from AttachmentStore (AD-731 invariant).
        try:
            from probos.routers.chat import _get_attachment_store
            store = _get_attachment_store(self._runtime)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "BF-666: attachment-store resolution failed unexpectedly "
                "before frame read sha=%s; latest-frame cache retained for "
                "transient recovery and frame skipped",
                sha[:8], exc_info=True,
            )
            return None
        try:
            frame_bytes = await store.read(sha)
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            removed = (
                self._clear_latest_frame_if_matches(read_candidate)
                if read_candidate is not None
                else 0
            )
            if removed:
                logger.debug(
                    "BF-666: AttachmentStore.read found frame absent sha=%s; "
                    "removed %d exact latest-frame alias(es), so future "
                    "describes skip the reaped blob",
                    sha[:8], removed,
                )
            return None
        except Exception:
            logger.warning(
                "BF-666: AttachmentStore.read failed unexpectedly sha=%s; "
                "latest-frame cache retained for transient retry and frame skipped",
                sha[:8], exc_info=True,
            )
            return None
        if not frame_bytes:
            logger.warning("AD-733a: attachment %s missing; skipping frame", sha[:8])
            return None

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
                return None
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
            return None
        async with self._describe_lock:
            # AD-742e: thread the current session_id into the consumer so the
            # budget counter's reset-on-session-change logic sees the right
            # bucket. Effective default when callers don't set session_id.
            if session_id:
                self._budget_current_session_id = session_id
            description = await self._describe(sha)
        if not description:
            logger.info("AD-733a: vision LLM returned empty for sha=%s", sha[:8])
            return None

        # 4) Write to every registered observer's WorkingMemory.
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
        # BF-617: record the latest observation for the shared-meeting fallback
        # (see ``latest_shared_observation``). Set before fan-out so a frame is
        # shareable even when the fan-out target set is empty.
        self._last_observation = obs
        # AD-742c: when the uploader bound the frame to specific agents,
        # restrict fan-out to that set (intersected with registered
        # observers). When the params key is absent, fall back to legacy
        # fan-out-to-all behavior (AD-733a default).
        _bound_raw = msg.params.get("bound_agent_ids")
        _bound: set[str] | None = None
        if isinstance(_bound_raw, (list, tuple)) and _bound_raw:
            _bound = {str(aid) for aid in _bound_raw if isinstance(aid, str) and aid}
        if _bound is not None:
            fan_out_targets = [
                aid for aid in self._observer_agent_ids if aid in _bound
            ]
        else:
            fan_out_targets = list(self._observer_agent_ids)
        # AD-746 Layer 2: filter fan-out by each agent's per-profile
        # ``bound_sources``. Default value is ``["camera", "screen"]``
        # so agents that haven't been bound explicitly see all sources
        # (back-compat). When an agent's binding doesn't intersect the
        # frame's sources, it's dropped for THAT agent — both WM and
        # the anchor (which scopes per-agent recall).
        fan_out_targets = self._filter_by_bound_sources(
            fan_out_targets, sources_list,
        )
        for agent_id in fan_out_targets:
            wm = get_or_create_working_memory(agent_id, capacity=self._wm_capacity)
            wm.append(obs)

        # 5) Anchor an episode (AD-541b — importance=6, lower than camera_began=8).
        # BF-311: tag with the observer agent_ids so per-agent episodic recall
        # can surface these episodes. Without this, ``agent_ids_json = []``
        # and the episodes are invisible to every agent's recall query —
        # they exist in chroma but aren't retrievable, which silently breaks
        # the AD-541b promise that perception observations form long-term memory.
        # AD-742c: when bound to specific agents, the anchor only sees that
        # subset so per-agent recall scopes correctly.
        anchor_agent_ids = list(fan_out_targets)
        await self._anchor_episode(
            sha, description, novelty_score, session_id,
            agent_ids=anchor_agent_ids,
            sources=sources_list,
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
        return obs

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
        async with self._force_describe_permit() as acquired:
            if not acquired:
                logger.debug(
                    "BF-666: force_describe dropped concurrent call for session=%s; "
                    "existing call owns the current snapshot",
                    str(session_id or "*")[:8],
                )
                return None

            candidate = self._select_latest_frame(session_id)
            if candidate is None:
                logger.debug(
                    "AD-733c-1: force_describe — no cached frame for session=%s",
                    str(session_id or "*")[:8],
                )
                return None
            sha, captured_at = candidate
            max_age = self._force_describe_max_age_seconds()
            age = max(0.0, time.time() - captured_at)
            if age > max_age:
                removed = self._clear_latest_frame_if_matches(candidate)
                if removed:
                    logger.debug(
                        "BF-666: force_describe rejected expired frame sha=%s "
                        "age=%.3fs max_age=%.3fs; removed %d exact alias(es) "
                        "before storage work",
                        sha[:8], age, max_age, removed,
                    )
                return None

            try:
                from probos.routers.chat import _get_attachment_store
                store = _get_attachment_store(self._runtime)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "BF-666: attachment-store resolution failed unexpectedly "
                    "during force_describe sha=%s; latest-frame cache retained "
                    "for transient recovery and DM proceeds without a fresh frame",
                    sha[:8], exc_info=True,
                )
                return None
            try:
                exists = await store.exists(sha)
            except asyncio.CancelledError:
                raise
            except FileNotFoundError:
                exists = False
            except Exception:
                logger.warning(
                    "BF-666: AttachmentStore.exists preflight failed "
                    "unexpectedly sha=%s; latest-frame cache retained for "
                    "transient retry and DM proceeds without a fresh frame",
                    sha[:8], exc_info=True,
                )
                return None
            if not exists:
                removed = self._clear_latest_frame_if_matches(candidate)
                if removed:
                    logger.debug(
                        "BF-666: force_describe preflight found frame absent "
                        "sha=%s; removed %d exact alias(es), so future calls "
                        "skip storage",
                        sha[:8], removed,
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
                produced_observation = await asyncio.wait_for(
                    self._process(synthetic, cache_candidate=candidate),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "AD-733c-1: force_describe timed out after %.1fs sha=%s",
                    timeout_s, sha[:8],
                )
                return None
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "AD-733c-1: force_describe raised for sha=%s; DM proceeds without fresh frame",
                    sha[:8], exc_info=True,
                )
                return None

            try:
                still_exists = await store.exists(sha)
            except asyncio.CancelledError:
                raise
            except FileNotFoundError:
                still_exists = False
            except Exception:
                logger.warning(
                    "BF-666: AttachmentStore.exists postcheck failed "
                    "unexpectedly sha=%s; latest-frame cache retained and any "
                    "completed working-memory observation remains available",
                    sha[:8], exc_info=True,
                )
                still_exists = True
            if not still_exists:
                removed = self._clear_latest_frame_if_matches(candidate)
                if removed:
                    logger.debug(
                        "BF-666: force_describe postcheck found frame reaped "
                        "sha=%s; removed %d exact alias(es) without undoing "
                        "completed working-memory work",
                        sha[:8], removed,
                    )
                return None

            if (
                produced_observation is None
                or produced_observation.attachment_ref != sha
            ):
                return None
            return produced_observation.description

    def record_uploaded_frame(
        self, sha: str, session_id: str, captured_at: float
    ) -> None:
        """AD-746a: mirror the latest-frame cache at upload time.

        Defense-in-depth for FORCE DESCRIBE. The router endpoint calls this
        when it accepts a camera/screen frame, BEFORE broadcasting the
        ``vision_observation`` intent — so ``force_describe_current_frame``
        has a warm SHA even if the VisionAggregator buffers/deadlocks and
        never forwards the frame to ``_handle`` (BF-323). Idempotent with the
        ``_handle`` write: both store ``(sha, captured_at)`` keyed by session
        plus the global slot. No-op on empty sha.
        """
        self._record_latest_frame(sha, session_id, captured_at)

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
            # BF-316: small VLMs (qwen2.5vl:3b) confabulate scenes from
            # contextual priors — a webcam frame + a framed photo on the
            # shelf gets described as "split-screen video call with multiple
            # participants." Explicit anti-confabulation anchors (photos as
            # objects, no scene inference) protect Ezri's episodic memory
            # from being seeded with invented context.
            if describe_tier == self._fast_tier:
                prompt = (
                    "Describe what is literally visible in this image in one or two sentences. "
                    "Include any person and what they are wearing. "
                    "Treat framed pictures, photos, posters, and screens as objects on furniture "
                    "or walls — not as additional people or video call participants. "
                    "Do not infer activities (such as 'video call' or 'meeting') unless directly shown. "
                    "Do not invent details."
                )
                temperature = 0.0
                max_tokens = 100
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
        sources: list[str] | None = None,
    ) -> None:
        episodic = getattr(self._runtime, "episodic_memory", None)
        if episodic is None:
            return
        try:
            # AD-746 Layer 1 + AD-541b: ``sources`` list carries the full
            # source provenance (camera, screen, or both for fused
            # frames). The legacy ``source`` field stays as a one-wave
            # forward-compat alias (writes the first element).
            sources_value = list(sources) if sources else ["camera"]
            outcome: dict[str, Any] = {
                "intent": "vision_observation",
                "success": True,
                "session_id": session_id,
                "attachment_ref": sha,
                "novelty_score": novelty,
                "sources": sources_value,
                "source": sources_value[0],  # AD-746-5 retires this alias.
            }
            episode = Episode(
                timestamp=time.time(),
                user_input="",
                outcomes=[outcome],
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

    def _filter_by_bound_sources(
        self, agent_ids: list[str], sources_list: list[str],
    ) -> list[str]:
        """AD-746 Layer 2: drop agents whose ``bound_sources`` does not
        intersect the frame's sources.

        Default per-agent ``bound_sources`` is ``["camera", "screen"]``
        (back-compat — agents see both). For fused frames (multiple
        sources), an agent passes if AT LEAST ONE of the fused sources
        is in their binding (so a camera-bound Counselor still sees a
        fused camera+screen tick because the camera half is relevant).

        Honest-degrade: when no profile_store is available, the filter
        is bypassed (pre-AD-746 behavior preserved).
        """
        profile_store = getattr(self._runtime, "profile_store", None)
        if profile_store is None:
            return list(agent_ids)
        frame_sources = set(sources_list)
        kept: list[str] = []
        for aid in agent_ids:
            try:
                profile = profile_store.get(aid)
            except Exception:
                profile = None
            if profile is None or getattr(profile, "perception", None) is None:
                # No profile binding → default = see all sources.
                kept.append(aid)
                continue
            bound = getattr(profile.perception, "bound_sources", None)
            # Only treat ``bound`` as a real binding when it's a
            # concrete list/tuple of strings. MagicMock-shaped values
            # in tests fall through to the legacy "see all" path so
            # pre-AD-746 fixtures stay green.
            if not isinstance(bound, (list, tuple)) or not bound:
                kept.append(aid)
                continue
            bound_set = {s for s in bound if isinstance(s, str)}
            if not bound_set:
                kept.append(aid)
                continue
            if frame_sources & bound_set:
                kept.append(aid)
        return kept


__all__ = [
    "VisionConsumer",
    "get_or_create_working_memory",
    "reset_working_memories_for_tests",
]
