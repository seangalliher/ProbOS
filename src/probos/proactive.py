"""Proactive Cognitive Loop — periodic idle-think for crew agents (Phase 28b)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from probos.config import format_trust
from probos.crew_profile import Rank
from probos.crew_utils import is_crew_agent
from probos.events import EventType
from probos.duty_schedule import DutyScheduleTracker
from probos.earned_agency import AgencyLevel, agency_from_rank, can_think_proactively
from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
from probos.cognitive.orientation import OrientationContext, derive_watch_section
from probos.types import AnchorFrame, IntentMessage
from probos.utils import format_duration

if TYPE_CHECKING:
    from probos.config import DutyScheduleConfig, ProactiveCognitiveConfig
    from probos.knowledge.store import KnowledgeStore
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


def collect_notebook_metrics(runtime: Any, agent_id: str = "") -> dict[str, Any]:
    """AD-553: Collect standardized metrics snapshot for notebook attachment.

    Returns flat dict of metric_name -> value. Degrades gracefully:
    returns empty dict if runtime/VitalsMonitor unavailable.
    """
    metrics: dict[str, Any] = {}
    if runtime is None:
        return metrics

    # VitalsMonitor cached data (no I/O)
    vitals = None
    try:
        for agent in runtime.registry.all():
            if getattr(agent, "agent_type", "") == "vitals_monitor":
                vitals = agent.latest_vitals
                break
    except Exception:
        pass  # Registry unavailable

    if vitals:
        for key in ("trust_mean", "trust_min", "system_health"):
            val = vitals.get(key)
            if val is not None:
                metrics[key] = round(val, 3)

        # Pool health mean
        pool_health = vitals.get("pool_health")
        if pool_health and isinstance(pool_health, dict):
            vals = [v for v in pool_health.values() if isinstance(v, (int, float))]
            if vals:
                metrics["pool_health_mean"] = round(sum(vals) / len(vals), 3)

        # Emergence (AD-557)
        for key in ("emergence_capacity", "coordination_balance"):
            val = vitals.get(key)
            if val is not None:
                metrics[key] = round(val, 3)

        # LLM health
        llm = vitals.get("llm_health")
        if isinstance(llm, dict):
            overall = llm.get("overall")
            if overall:
                metrics["llm_health"] = overall

    # Agent's own trust score
    if agent_id and hasattr(runtime, "trust_network") and runtime.trust_network:
        try:
            score = runtime.trust_network.get_score(agent_id)
            if score is not None:
                metrics["agent_trust"] = round(score, 3)
        except Exception:
            pass

    # Active agent count
    try:
        metrics["active_agents"] = len(runtime.registry.all())
    except Exception:
        pass

    return metrics


def compute_metrics_delta(
    old_metrics: dict[str, Any],
    new_metrics: dict[str, Any],
    *,
    min_numeric_delta: float = 0.01,
) -> dict[str, Any]:
    """AD-553: Compute delta between two metrics snapshots.

    Returns dict of metric_name -> delta for numeric values that changed
    by more than min_numeric_delta, and "old -> new" strings for changed
    string values. Returns empty dict if no meaningful changes.
    """
    delta: dict[str, Any] = {}
    all_keys = set(old_metrics) | set(new_metrics)

    for key in sorted(all_keys):
        old_val = old_metrics.get(key)
        new_val = new_metrics.get(key)

        if old_val is None or new_val is None:
            continue  # Skip if either side is missing

        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            diff = new_val - old_val
            if abs(diff) >= min_numeric_delta:
                delta[key] = round(diff, 3)
        elif isinstance(old_val, str) and isinstance(new_val, str):
            if old_val != new_val:
                delta[key] = f"{old_val} \u2192 {new_val}"

    return delta


class ProactiveCognitiveLoop:
    """Periodic idle-think cycle for crew agents.

    Every ``interval`` seconds, iterates crew agents sequentially.
    For each agent with sufficient trust (Lieutenant+), gathers recent
    context (episodic memory, bridge alerts, system events) and sends
    a ``proactive_think`` intent. If the agent's LLM produces a meaningful
    response (not ``[NO_RESPONSE]``), creates a Ward Room thread in the
    agent's department channel.

    Follows the InitiativeEngine pattern: asyncio.create_task, fail-open,
    CancelledError propagation.
    """

    # BF-039: Cold-start episode dampening — 3x cooldown for this window
    COLD_START_WINDOW_SECONDS = 600  # 10 minutes

    def __init__(
        self,
        *,
        interval: float = 120.0,
        cooldown: float = 300.0,
        on_event: Callable[[dict], Any] | None = None,
    ) -> None:
        self._interval = interval
        self._cooldown = cooldown
        self._on_event = on_event
        self._last_proactive: dict[str, float] = {}  # agent_id -> monotonic timestamp
        self._agent_cooldowns: dict[str, float] = {}  # agent_id -> override cooldown (seconds)
        self._cooldown_reasons: dict[str, str] = {}  # agent_id -> reason text (AD-505)
        self._knowledge_store: KnowledgeStore | None = None  # AD-415: Set by runtime for persistence
        self._task: asyncio.Task | None = None
        self._runtime: ProbOSRuntime | None = None  # Set via set_runtime()
        self._started_at: float = time.monotonic()  # BF-039: cold-start reference
        self._config: ProactiveCognitiveConfig | None = None   # Set via set_config()
        self._duty_tracker: DutyScheduleTracker | None = None
        self._circuit_breaker = CognitiveCircuitBreaker()
        self._notified_dm_threads: set[str] = set()  # BF-082: dedup guard
        self._notified_dm_threads_reset: float = time.monotonic()  # hourly reset
        self._pending_notebook_reads: dict[str, str] = {}  # AD-504: agent_id -> topic_slug
        self._llm_failure_count: int = 0  # BF-069: consecutive proactive failures
        self._llm_failure_streak: int = 0  # BF-069: consecutive cycles with failure
        self._orientation_service: Any = None  # AD-567g: Late-bound

    def set_runtime(self, runtime: ProbOSRuntime) -> None:
        """Wire the runtime reference (provides registry, trust, WR, memory, etc.)."""
        self._runtime = runtime

    def set_config(self, config: ProactiveCognitiveConfig, cb_config: Any = None) -> None:
        """Store ProactiveCognitiveConfig for trust signal weights (AD-414)."""
        self._config = config
        if cb_config:
            from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
            self._circuit_breaker = CognitiveCircuitBreaker(config=cb_config)

    @property
    def circuit_breaker(self) -> CognitiveCircuitBreaker:
        """Expose circuit breaker for runtime wiring and API access."""
        return self._circuit_breaker

    @property
    def _default_cooldown(self) -> float:
        return self._cooldown

    def set_duty_schedule(self, config: DutyScheduleConfig | None) -> None:
        """Initialize duty schedule tracker from DutyScheduleConfig."""
        if config and config.enabled and config.schedules:
            self._duty_tracker = DutyScheduleTracker(config.schedules)
            logger.info("Duty schedule loaded: %d agent types configured",
                         len(config.schedules))
        else:
            self._duty_tracker = None

    def get_agent_cooldown(self, agent_id: str) -> float:
        """Get effective cooldown for an agent (override or global default)."""
        return self._agent_cooldowns.get(agent_id, self._cooldown)

    def get_cooldown_reason(self, agent_id: str) -> str:
        """Return the reason for a cooldown override, or empty string."""
        return self._cooldown_reasons.get(agent_id, "")

    def clear_counselor_cooldown(self, agent_id: str) -> None:
        """Remove a Counselor-set cooldown override, restoring the default."""
        if agent_id in self._agent_cooldowns:
            del self._agent_cooldowns[agent_id]
        if agent_id in self._cooldown_reasons:
            del self._cooldown_reasons[agent_id]
        self._persist_cooldowns()

    def set_agent_cooldown(self, agent_id: str, cooldown: float, reason: str = "") -> None:
        """Set per-agent proactive cooldown override. Clamp to [60, 1800]."""
        cooldown = max(60.0, min(1800.0, cooldown))
        self._agent_cooldowns[agent_id] = cooldown
        if reason:
            self._cooldown_reasons[agent_id] = reason
        elif agent_id in self._cooldown_reasons:
            del self._cooldown_reasons[agent_id]
        # AD-415: Write-through to KnowledgeStore
        self._persist_cooldowns()

    def _persist_cooldowns(self) -> None:
        """AD-415: Fire-and-forget persistence of cooldown overrides."""
        if not self._knowledge_store:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._knowledge_store.store_cooldowns(self._agent_cooldowns.copy()))
        except RuntimeError:
            pass  # No event loop — skip persistence (e.g., during shutdown)

    async def restore_cooldowns(self) -> None:
        """AD-415: Restore per-agent cooldowns from KnowledgeStore on boot."""
        if not self._knowledge_store:
            return
        try:
            saved = await self._knowledge_store.load_cooldowns()
            if saved:
                for agent_id, cooldown in saved.items():
                    # Apply same clamping as set_agent_cooldown
                    self._agent_cooldowns[agent_id] = max(60.0, min(1800.0, cooldown))
        except Exception:
            logger.info("Failed to restore proactive cooldowns — agents may be temporarily over-active", exc_info=True)

    async def start(self) -> None:
        """Start the periodic think loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._think_loop())

    async def stop(self) -> None:
        """Stop the think loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _think_loop(self) -> None:
        """Main loop: iterate agents every interval seconds."""
        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ProactiveCognitiveLoop cycle failed (fail-open)")
            await asyncio.sleep(self._interval)

    async def _run_cycle(self) -> None:
        """One think cycle: iterate all crew agents sequentially."""
        rt = self._runtime
        if not rt or not rt.ward_room:
            return

        for agent in rt.registry.all():
            if not is_crew_agent(agent, rt.ontology):
                continue
            if not agent.is_alive:
                continue

            # Agency gating: Ensigns don't think proactively
            trust_score = rt.trust_network.get_score(agent.id)
            rank = Rank.from_trust(trust_score)
            if not can_think_proactively(rank):
                continue

            # Cooldown: skip if agent posted proactively recently
            last = self._last_proactive.get(agent.id, 0.0)
            cooldown = self.get_agent_cooldown(agent.id)
            # BF-039: Cold-start dampening — 3x cooldown for first N minutes
            if time.monotonic() - self._started_at < self.COLD_START_WINDOW_SECONDS:
                cooldown *= 3
            if time.monotonic() - last < cooldown:
                continue

            # AD-488: Circuit breaker gate — skip agents in cognitive cooldown
            if not self._circuit_breaker.should_allow_think(agent.id):
                breaker_status = self._circuit_breaker.get_status(agent.id)
                logger.debug(
                    "AD-488: %s circuit breaker OPEN (trip #%d, cooldown %.0fs remaining)",
                    getattr(agent, 'callsign', agent.agent_type),
                    breaker_status['trip_count'],
                    breaker_status['cooldown_seconds'] - (time.monotonic() - breaker_status['tripped_at']),
                )
                continue

            # AD-442: Check probationary → active transition
            if rt.acm and rt.trust_network:
                try:
                    _onb = getattr(getattr(rt, 'config', None), 'onboarding', None)
                    _act_thresh = float(getattr(_onb, 'activation_trust_threshold', 0.65)) if _onb else 0.65
                    _tscore = rt.trust_network.get_score(agent.id)
                    if isinstance(_tscore, (int, float)) and _tscore >= _act_thresh:
                        activated = await rt.acm.check_activation(agent.id, _tscore, _act_thresh)
                        if activated:
                            logger.info("AD-442: %s activated (trust=%.2f)", getattr(agent, 'callsign', agent.id), _tscore)
                except Exception:
                    logger.debug("ACM activation check failed for agent", exc_info=True)

            try:
                await self._think_for_agent(agent, rank, trust_score)
            except Exception:
                # BF-023: Track the failure so confidence reflects reality.
                # Without this, LLM exceptions leave confidence frozen and
                # agents stay permanently degraded with no recovery path.
                agent.update_confidence(False)
                logger.debug(
                    "Proactive think failed for %s (fail-open, confidence=%.3f)",
                    agent.agent_type,
                    agent.confidence,
                    exc_info=True,
                )

            # --- BF-082: Unread DM check ---
            await self._check_unread_dms(agent, rt)

    async def _check_unread_dms(self, agent: Any, rt: Any) -> None:
        """Check for and route unread DMs for an agent."""
        if not rt.ward_room or not rt.ward_room_router:
            return

        # Hourly reset of dedup set to allow re-notification of stale DMs
        if time.monotonic() - self._notified_dm_threads_reset > 3600:
            self._notified_dm_threads.clear()
            self._notified_dm_threads_reset = time.monotonic()

        try:
            unread_dms = await rt.ward_room.get_unread_dms(agent.id, limit=2)
            if not unread_dms:
                return

            for dm in unread_dms:
                tid = dm["thread_id"]
                if tid in self._notified_dm_threads:
                    continue
                self._notified_dm_threads.add(tid)
                # Route through existing notification pipeline
                event_data = {
                    "thread_id": tid,
                    "channel_id": dm["channel_id"],
                    "author_id": dm["author_id"],
                    "author_callsign": dm["author_callsign"],
                    "title": dm["title"],
                    "body": dm["body"],
                }
                await rt.ward_room_router.route_event(
                    "ward_room_thread_created", event_data,
                )
            logger.info(
                "BF-082: %s has %d unread DMs, notified",
                getattr(agent, 'callsign', agent.agent_type),
                len(unread_dms),
            )
        except Exception as exc:
            logger.warning(
                "BF-082: Unread DM check failed for %s: %s",
                agent.agent_type, exc,
            )

    async def _think_for_agent(self, agent: Any, rank: Rank, trust_score: float) -> None:
        """Gather context, send proactive_think intent, post result if meaningful.

        AD-419: If a duty is due, send a duty-specific prompt. If no duty is due,
        send a free-form think prompt that requires justification.
        """
        rt = self._runtime
        context_parts = await self._gather_context(agent, trust_score)

        # AD-419: Check duty schedule
        duty = None
        if self._duty_tracker:
            due_duties = self._duty_tracker.get_due_duties(agent.agent_type)
            if due_duties:
                duty = due_duties[0]  # Highest priority
            else:
                # BF-021 refined: No duty due — allow free-form thinks but at
                # reduced frequency (3x cooldown). Agents stay alive between
                # duty cycles instead of going completely dark.
                # BF-025: Guard with last > 0 so first-ever think always passes.
                # time.monotonic() on fresh CI runners can be < idle_cooldown.
                last = self._last_proactive.get(agent.id, 0.0)
                idle_cooldown = self.get_agent_cooldown(agent.id) * 3
                if last > 0 and time.monotonic() - last < idle_cooldown:
                    return

        # AD-417: Record proactive activity for dream scheduler awareness
        if hasattr(self._runtime, 'dream_scheduler') and self._runtime.dream_scheduler:
            self._runtime.dream_scheduler.record_proactive_activity()

        # AD-502: Inject post count for temporal awareness
        try:
            rt = self._runtime
            if rt and hasattr(rt, 'ward_room') and rt.ward_room:
                one_hour_ago = time.time() - 3600
                cooldown_ts = rt._ward_room_cooldowns.get(agent.id, 0)
                # Count as 1 if posted within the last hour, 0 otherwise
                # This is a rough proxy — exact count would require WR query
                agent._recent_post_count = 1 if cooldown_ts > one_hour_ago else 0
            else:
                agent._recent_post_count = 0
        except Exception:
            logger.debug("Recent post count tracking failed", exc_info=True)

        intent = IntentMessage(
            intent="proactive_think",
            params={
                "context_parts": context_parts,
                "trust_score": format_trust(trust_score),
                "agency_level": agency_from_rank(rank).value,
                "rank": rank.value,  # AD-437: for action space awareness
                "agent_type": agent.agent_type,
                "duty": {
                    "duty_id": duty.duty_id,
                    "description": duty.description,
                } if duty else None,
            },
            target_agent_id=agent.id,
        )

        result = await agent.handle_intent(intent)

        if not result or not result.success or not result.result:
            self._llm_failure_count += 1
            # BF-069: Log failure details for visibility
            error_detail = ""
            if result and hasattr(result, 'error') and result.error:
                error_detail = str(result.error)
            elif result and not result.success:
                error_detail = "agent returned unsuccessful result"
            if error_detail:
                logger.warning(
                    "BF-069: Proactive think failed for %s: %s (consecutive failures: %d)",
                    agent.agent_type, error_detail, self._llm_failure_count,
                )
            return

        response_text = str(result.result).strip()
        if not response_text or "[NO_RESPONSE]" in response_text:
            # Record duty execution even if agent had nothing to report
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            # AD-414: Optional trust signal for disciplined silence
            if self._config:
                no_response_weight = self._config.trust_no_response_weight
                if no_response_weight > 0:
                    self._runtime.trust_network.record_outcome(
                        agent.id,
                        success=True,
                        weight=no_response_weight,
                        intent_type="proactive_no_response",
                    )
            # AD-430a: Store no-response as episodic memory (prevents redundant re-analysis)
            if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
                try:
                    from probos.types import AnchorFrame, Episode, MemorySource
                    callsign = ""
                    if hasattr(rt, 'callsign_registry'):
                        callsign = rt.callsign_registry.get_callsign(agent.agent_type)

                    # AD-567a: Resolve department for anchor
                    _dept = ""
                    try:
                        _ont = getattr(rt, 'ontology', None)
                        if _ont:
                            _dept = _ont.get_agent_department(agent.agent_type) or ""
                        if not _dept:
                            from probos.cognitive.standing_orders import get_department as _get_dept
                            _dept = _get_dept(agent.agent_type) or ""
                    except Exception:
                        pass

                    episode = Episode(
                        user_input=f"[Proactive thought — no response] {callsign or agent.agent_type}: reviewed context, nothing to report",
                        timestamp=time.time(),
                        agent_ids=[getattr(agent, 'sovereign_id', None) or agent.id],
                        outcomes=[{
                            "intent": "proactive_think",
                            "success": True,
                            "response": "[NO_RESPONSE]",
                            "duty_id": duty.duty_id if duty else None,
                            "agent_type": agent.agent_type,
                        }],
                        reflection=f"{callsign or agent.agent_type} reviewed context but had nothing to report.",
                        source=MemorySource.DIRECT,
                        anchors=AnchorFrame(
                            channel="duty_report",
                            duty_cycle_id=duty.duty_id if duty else "",
                            department=_dept,
                            trigger_type="duty_cycle" if duty else "proactive_think",
                            watch_section=derive_watch_section(),
                            event_log_window=float(len(rt.event_log.recent(seconds=60))) if hasattr(rt, 'event_log') and hasattr(rt.event_log, 'recent') else 0.0,
                        ),
                    )
                    from probos.cognitive.episodic import EpisodicMemory
                    if EpisodicMemory.should_store(episode):
                        await rt.episodic_memory.store(episode)
                except Exception:
                    logger.debug("Failed to store no-response episode for %s", agent.agent_type, exc_info=True)
            # AD-488: Record no-response as event (rapid no-responses can also indicate loops)
            self._circuit_breaker.record_event(agent.id, "no_response", "")
            return

        # BF-032: Skip if too similar to agent's recent posts
        if await self._is_similar_to_recent_posts(agent, response_text):
            logger.debug(
                "BF-032: Suppressed similar proactive post from %s",
                agent.agent_type,
            )
            # Still record duty execution if applicable
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return

        # AD-437: Extract and process structured actions from proactive response
        cleaned_text, actions_taken = await self._extract_and_execute_actions(
            agent, response_text
        )
        if cleaned_text != response_text:
            response_text = cleaned_text

        # AD-412: Check for structured improvement proposals
        await self._extract_and_post_proposal(agent, response_text)

        # Post to Ward Room — find agent's department channel
        await self._post_to_ward_room(agent, response_text)
        self._last_proactive[agent.id] = time.monotonic()
        self._llm_failure_count = 0  # BF-069: reset on successful post

        # AD-488: Record cognitive event and check for rumination
        self._circuit_breaker.record_event(
            agent.id,
            "proactive_think",
            response_text[:500] if response_text else "",
        )
        # AD-488: Record Ward Room post as cognitive event
        self._circuit_breaker.record_event(
            agent.id,
            "ward_room_post",
            response_text[:500] if response_text else "",
        )
        if self._circuit_breaker.check_and_trip(agent.id):
            # Breaker tripped — fire bridge alert for Counselor awareness
            if self._on_event:
                callsign = getattr(agent, 'callsign', agent.agent_type)
                self._on_event({
                    "type": EventType.BRIDGE_ALERT.value,
                    "source": "circuit_breaker",
                    "severity": "warning",
                    "title": f"Circuit Breaker: {callsign}",
                    "detail": (
                        f"{callsign}'s cognitive circuit breaker has activated "
                        f"(trip #{self._circuit_breaker.get_status(agent.id)['trip_count']}). "
                        "Repetitive thought patterns detected. "
                        "Forced cooldown applied — not punishment, health protection."
                    ),
                })
            # AD-503/AD-495: Emit circuit_breaker_trip event for Counselor subscription
            if self._on_event:
                breaker_status = self._circuit_breaker.get_status(agent.id)
                self._on_event({
                    "type": EventType.CIRCUIT_BREAKER_TRIP.value,
                    "data": {
                        "agent_id": agent.id,
                        "agent_type": agent.agent_type,
                        "callsign": getattr(agent, "callsign", ""),
                        "trip_count": breaker_status.get("trip_count", 1),
                        "cooldown_seconds": breaker_status.get("cooldown_seconds", 900.0),
                        "trip_reason": breaker_status.get("trip_reason", "unknown"),
                        "zone": breaker_status.get("zone", "red"),  # AD-506a
                    },
                })
        else:
            # AD-506a: Check zone and emit concern if amber (not tripped)
            zone = self._circuit_breaker.get_zone(agent.id)
            if zone == "amber" and self._on_event:
                status = self._circuit_breaker.get_status(agent.id)
                self._on_event({
                    "type": EventType.SELF_MONITORING_CONCERN.value,
                    "data": {
                        "agent_id": agent.id,
                        "agent_callsign": getattr(agent, "callsign", ""),
                        "zone": "amber",
                        "similarity_ratio": status.get("similarity_ratio", 0.0),
                        "velocity_ratio": status.get("velocity_ratio", 0.0),
                    },
                })

        # AD-506b: Emit zone recovery event
        transition = self._circuit_breaker.get_last_zone_transition(agent.id)
        if transition and self._on_event:
            old_zone, new_zone = transition
            # Recovery = zone improved (lower severity)
            zone_order = {"green": 0, "amber": 1, "red": 2, "critical": 3}
            if zone_order.get(new_zone, 0) < zone_order.get(old_zone, 0):
                self._on_event({
                    "type": EventType.ZONE_RECOVERY.value,
                    "data": {
                        "agent_id": agent.id,
                        "agent_callsign": getattr(agent, "callsign", ""),
                        "old_zone": old_zone,
                        "new_zone": new_zone,
                    },
                })

        # AD-414: Emit attenuated trust signal for successful proactive think
        if self._config:
            trust_weight = self._config.trust_reward_weight
            if duty:
                trust_weight += self._config.trust_duty_bonus  # Duty completion bonus
            if trust_weight > 0:
                new_score = self._runtime.trust_network.record_outcome(
                    agent.id,
                    success=True,
                    weight=trust_weight,
                    intent_type="proactive_think",
                )

        # Record duty execution after successful post
        if duty and self._duty_tracker:
            self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)

        # AD-430a: Store proactive thought as episodic memory
        # BF-039: Skip if posted to Ward Room — WR creates its own episode,
        # storing here too would be a duplicate.
        wr_available = hasattr(rt, 'ward_room') and rt.ward_room
        if not wr_available and hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                from probos.types import AnchorFrame, Episode
                callsign = ""
                if hasattr(rt, 'callsign_registry'):
                    callsign = rt.callsign_registry.get_callsign(agent.agent_type)
                thought_summary = response_text[:200]

                # AD-567a: Resolve department for anchor
                _dept = ""
                try:
                    _ont = getattr(rt, 'ontology', None)
                    if _ont:
                        _dept = _ont.get_agent_department(agent.agent_type) or ""
                    if not _dept:
                        from probos.cognitive.standing_orders import get_department as _get_dept
                        _dept = _get_dept(agent.agent_type) or ""
                except Exception:
                    pass

                episode = Episode(
                    user_input=f"[Proactive thought] {callsign or agent.agent_type}: {thought_summary}",
                    timestamp=time.time(),
                    agent_ids=[getattr(agent, 'sovereign_id', None) or agent.id],
                    outcomes=[{
                        "intent": "proactive_think",
                        "success": True,
                        "response": response_text[:500],
                        "duty_id": duty.duty_id if duty else None,
                        "agent_type": agent.agent_type,
                    }],
                    reflection=f"{callsign or agent.agent_type} observed: {thought_summary}",
                    source=MemorySource.DIRECT,
                    anchors=AnchorFrame(
                        channel="duty_report",
                        duty_cycle_id=duty.duty_id if duty else "",
                        department=_dept,
                        trigger_type="duty_cycle" if duty else "proactive_think",
                        watch_section=derive_watch_section(),
                        event_log_window=float(len(rt.event_log.recent(seconds=60))) if hasattr(rt, 'event_log') and hasattr(rt.event_log, 'recent') else 0.0,
                    ),
                )
                from probos.cognitive.episodic import EpisodicMemory
                if EpisodicMemory.should_store(episode):
                    await rt.episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store proactive thought episode for %s", agent.agent_type, exc_info=True)

        if self._on_event:
            self._on_event({
                "type": EventType.PROACTIVE_THOUGHT.value,
                "data": {
                    "agent_id": agent.id,
                    "agent_type": agent.agent_type,
                    "response_length": len(response_text),
                    "duty_id": duty.duty_id if duty else None,
                },
            })

        logger.info(
            "Proactive thought from %s (%s): %d chars%s",
            agent.agent_type, rank.value, len(response_text),
            f" [duty: {duty.duty_id}]" if duty else " [free-form]",
        )

    async def _gather_context(self, agent: Any, trust_score: float) -> dict:
        """Gather recent context for the agent's proactive review."""
        rt = self._runtime
        context: dict[str, Any] = {}

        # AD-502: Temporal context for agent prompt
        if hasattr(rt, '_start_time_wall'):
            context["system_start_time"] = rt._start_time_wall
        if hasattr(rt, '_lifecycle_state'):
            context["lifecycle_state"] = rt._lifecycle_state
        if hasattr(rt, '_stasis_duration'):
            context["stasis_duration"] = rt._stasis_duration

        # BF-034: Cold-start context note for agents
        # AD-567g: Orientation subsumes this note when available
        _has_orientation = bool(getattr(agent, '_orientation_rendered', None))
        if not _has_orientation and hasattr(rt, 'is_cold_start') and rt.is_cold_start:
            context["system_note"] = (
                "SYSTEM NOTE: This is a fresh start after a system reset. "
                "All trust scores are at baseline (0.5). This is normal initialization, "
                "not a demotion. Build trust through demonstrated competence. "
                "You have no prior episodic memories — do not reference or invent past experiences."
            )

        # AD-567g: Proactive orientation supplement (diminishing)
        if getattr(self, '_orientation_service', None) and self._config:
            try:
                _ocfg = getattr(rt, 'config', None)
                if _ocfg and getattr(_ocfg, 'orientation', None) and _ocfg.orientation.proactive_supplement:
                    _birth = getattr(agent, '_birth_timestamp', None)
                    _age = (time.time() - _birth) if _birth else float('inf')
                    if _age < _ocfg.orientation.orientation_window_seconds:
                        _ep_count = 0
                        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
                            try:
                                _sid = getattr(agent, 'sovereign_id', None) or agent.id
                                _eps = await rt.episodic_memory.recall("", agent_id=_sid, k=1)
                                _ep_count = len(_eps) if _eps else 0
                            except Exception:
                                pass
                        _ctx = self._orientation_service.build_orientation(
                            agent,
                            lifecycle_state=getattr(rt, '_lifecycle_state', 'restart'),
                            episodic_memory_count=_ep_count,
                            trust_score=trust_score,
                        )
                        _ctx = OrientationContext(
                            **{
                                **{f.name: getattr(_ctx, f.name) for f in _ctx.__dataclass_fields__.values()},
                                'agent_age_seconds': _age,
                            }
                        )
                        _supp = self._orientation_service.render_proactive_orientation(_ctx)
                        if _supp:
                            context["orientation_supplement"] = _supp
            except Exception:
                logger.debug("AD-567g: proactive supplement failed", exc_info=True)

        # 1. Recent episodic memories (sovereign — only this agent's experiences)
        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                _agent_mem_id = getattr(agent, 'sovereign_id', None) or agent.id  # AD-441

                # AD-567b: Use salience-weighted recall with dynamic query
                em = rt.episodic_memory
                episodes = []
                if hasattr(em, 'recall_weighted'):
                    # Derive query from agent context instead of hardcoded "recent activity"
                    _duty_type = ""
                    query = f"{agent.agent_type} {_duty_type} recent duty observations".strip()

                    trust_net = getattr(rt, 'trust_network', None)
                    heb_router = getattr(rt, 'hebbian_router', None)
                    mem_cfg = None
                    if hasattr(rt, 'config') and hasattr(rt.config, 'memory'):
                        mem_cfg = rt.config.memory

                    scored_results = await em.recall_weighted(
                        _agent_mem_id, query,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                        k=5,
                        context_budget=getattr(mem_cfg, 'recall_context_budget_chars', 4000) if mem_cfg else 4000,
                        weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                        anchor_confidence_gate=getattr(mem_cfg, 'anchor_confidence_gate', 0.3) if mem_cfg else 0.3,
                    )
                    episodes = [rs.episode for rs in scored_results]

                # Fallback to old recall path
                if not episodes:
                    episodes = await em.recall_for_agent(
                        _agent_mem_id, "recent activity", k=5
                    )
                if not episodes and hasattr(em, 'recent_for_agent'):
                    episodes = await em.recent_for_agent(_agent_mem_id, k=5)

                if episodes:
                    # AD-502: Include relative timestamps on recalled memories
                    include_ts = True
                    if hasattr(rt, 'config') and hasattr(rt.config, 'temporal'):
                        include_ts = rt.config.temporal.include_episode_timestamps

                    memory_list = []
                    for ep in episodes:
                        mem = {
                            "input": (ep.user_input[:500] + " [trimmed]") if ep.user_input and len(ep.user_input) > 500 else (ep.user_input or ""),
                            "reflection": (ep.reflection[:500] + " [trimmed]") if ep.reflection and len(ep.reflection) > 500 else (ep.reflection or ""),
                            "source": getattr(ep, 'source', 'direct'),
                            "verified": False,  # AD-567b: proactive path parity
                        }
                        if include_ts and ep.timestamp > 0:
                            mem["age"] = format_duration(time.time() - ep.timestamp)
                        # AD-567b: Anchor context for formatting
                        anchors = getattr(ep, 'anchors', None)
                        if isinstance(anchors, AnchorFrame):
                            mem["anchor_channel"] = anchors.channel or ""
                            mem["anchor_department"] = anchors.department or ""
                            mem["anchor_participants"] = ", ".join(anchors.participants) if anchors.participants else ""
                            mem["anchor_trigger"] = anchors.trigger_type or ""
                        memory_list.append(mem)

                    context["recent_memories"] = memory_list
            except Exception:
                logger.debug("Episodic recall failed for %s", agent.id, exc_info=True)

        # 2. Recent bridge alerts
        if hasattr(rt, 'bridge_alerts') and rt.bridge_alerts:
            try:
                alerts = rt.bridge_alerts.get_recent_alerts(limit=5)
                if alerts:
                    context["recent_alerts"] = [
                        {
                            "severity": a.severity.value,
                            "title": a.title,
                            "source": a.source,
                        }
                        for a in alerts
                    ]
            except Exception:
                logger.debug("Bridge alerts fetch failed", exc_info=True)

        # 3. Recent system events
        if hasattr(rt, 'event_log') and rt.event_log:
            try:
                events = await rt.event_log.query(limit=10)
                if events:
                    context["recent_events"] = [
                        {
                            "category": e.get("category", ""),
                            "event": e.get("event", ""),
                            "agent_type": e.get("agent_type", ""),
                        }
                        for e in events[:10]
                    ]
            except Exception:
                logger.debug("Event log query failed", exc_info=True)

        # 4. Recent Ward Room activity in agent's department (AD-413)
        if hasattr(rt, 'ward_room') and rt.ward_room:
            try:
                from probos.cognitive.standing_orders import get_department
                # AD-429e: Prefer ontology, fall back to legacy dict
                ont = getattr(rt, 'ontology', None)
                dept = (ont.get_agent_department(agent.agent_type) if ont else None) or get_department(agent.agent_type)

                # BF-032: Build self-ID set for filtering own posts
                callsign = ""
                if hasattr(rt, 'callsign_registry'):
                    callsign = rt.callsign_registry.get_callsign(agent.agent_type)
                self_ids = {agent.id, agent.agent_type}
                if callsign:
                    self_ids.add(callsign)

                if dept:
                    channels = await rt.ward_room.list_channels()
                    dept_channel = None
                    all_hands_ch = None
                    for ch in channels:
                        if ch.channel_type == "department" and ch.department == dept:
                            dept_channel = ch
                        elif ch.channel_type == "ship":
                            all_hands_ch = ch

                    # Look back one cooldown window (what happened since last think)
                    cooldown = self._agent_cooldowns.get(agent.id, self._default_cooldown)
                    since = time.time() - cooldown

                    if dept_channel:
                        activity = await rt.ward_room.get_recent_activity(
                            dept_channel.id, since=since, limit=5
                        )
                        if activity:
                            context["ward_room_activity"] = [
                                {
                                    "type": a["type"],
                                    "author": a["author"],
                                    "body": a.get("title", a.get("body", ""))[:500],
                                    "net_score": a.get("net_score", 0),       # AD-426
                                    "post_id": a.get("post_id", a.get("id", "")),  # AD-426
                                    "thread_id": a.get("thread_id", ""),  # AD-437
                                }
                                for a in activity
                                if (a.get("author_id", "") or a.get("author", "")) not in self_ids  # BF-032
                            ]
                            # AD-425: Mark channel as seen after consuming activity
                            try:
                                await rt.ward_room.update_last_seen(agent.id, dept_channel.id)
                            except Exception:
                                logger.debug("update_last_seen failed", exc_info=True)

                    # AD-425: Also include recent All Hands activity (ship-wide)
                    if all_hands_ch and (not dept_channel or all_hands_ch.id != dept_channel.id):
                        all_hands_activity = await rt.ward_room.get_recent_activity(
                            all_hands_ch.id, since=since, limit=3
                        )
                        # Filter: only DISCUSS threads (INFORM already consumed, ACTION is targeted)
                        all_hands_filtered = [
                            a for a in all_hands_activity
                            if a.get("thread_mode") != "inform"
                        ]
                        if all_hands_filtered:
                            if "ward_room_activity" not in context:
                                context["ward_room_activity"] = []
                            context["ward_room_activity"].extend([
                                {
                                    "type": item["type"],
                                    "author": item.get("author", "unknown"),
                                    "body": item.get("body", "")[:500],
                                    "channel": "All Hands",
                                    "net_score": item.get("net_score", 0),       # AD-426
                                    "post_id": item.get("post_id", item.get("id", "")),  # AD-426
                                    "thread_id": item.get("thread_id", ""),  # AD-437
                                }
                                for item in all_hands_filtered[:3]
                                if (item.get("author_id", "") or item.get("author", "")) not in self_ids  # BF-032
                            ])
                            # AD-425: Mark All Hands as seen
                            try:
                                await rt.ward_room.update_last_seen(agent.id, all_hands_ch.id)
                            except Exception:
                                logger.debug("update_last_seen failed", exc_info=True)

                    # AD-526a: Recreation channel activity
                    rec_ch = next((c for c in channels if c.name == "Recreation"), None)
                    if rec_ch:
                        rec_items = await rt.ward_room.get_recent_activity(
                            rec_ch.id, limit=2, since=agent_last_seen.get(rec_ch.id)
                        )
                        rec_filtered = [
                            item for item in rec_items
                            if (item.get("author_id", "") or item.get("author", "")) not in self_ids
                        ]
                        if rec_filtered:
                            if "ward_room_activity" not in context:
                                context["ward_room_activity"] = []
                            context["ward_room_activity"].extend([
                                {
                                    "type": item["type"],
                                    "author": item.get("author", "unknown"),
                                    "body": item.get("body", "")[:500],
                                    "channel": "Recreation",
                                    "net_score": item.get("net_score", 0),
                                    "post_id": item.get("post_id", item.get("id", "")),
                                    "thread_id": item.get("thread_id", ""),
                                }
                                for item in rec_filtered[:2]
                            ])
            except Exception:
                logger.debug("Ward Room context fetch failed for %s", agent.id, exc_info=True)

        # BF-110: Inject active game state so agent can see the board and know it's their turn
        rec_svc = getattr(rt, 'recreation_service', None)
        if rec_svc:
            try:
                callsign = ""
                if hasattr(rt, 'callsign_registry'):
                    callsign = rt.callsign_registry.get_callsign(agent.agent_type)
                if callsign:
                    for game in rec_svc.get_active_games():
                        state = game.get("state", {})
                        players = [game.get("challenger", ""), game.get("opponent", "")]
                        if callsign in players:
                            board = rec_svc.render_board(game["game_id"])
                            valid_moves = rec_svc.get_valid_moves(game["game_id"])
                            is_my_turn = state.get("current_player") == callsign
                            context["active_game"] = {
                                "game_id": game["game_id"],
                                "game_type": game.get("game_type", ""),
                                "opponent": next((p for p in players if p != callsign), ""),
                                "is_my_turn": is_my_turn,
                                "board": board,
                                "valid_moves": valid_moves,
                                "moves_count": game.get("moves_count", 0),
                            }
                            break  # One active game at a time
            except Exception:
                logger.debug("BF-110: Game context injection failed for %s", agent.id, exc_info=True)

        # 5. Ontology context (AD-429a) — formal identity grounding
        if hasattr(rt, 'ontology') and rt.ontology:
            try:
                crew_ctx = rt.ontology.get_crew_context(agent.agent_type)
                if crew_ctx:
                    context["ontology"] = crew_ctx
            except Exception:
                logger.debug("Ontology context fetch failed for %s", agent.id, exc_info=True)

        # 6. Skill profile context (AD-429b)
        if hasattr(rt, 'skill_service') and rt.skill_service:
            try:
                profile = await rt.skill_service.get_profile(agent.id)
                if profile:
                    skill_summary = []
                    for record in profile.all_skills:
                        skill_summary.append(f"{record.skill_id}: level {record.proficiency.value} ({record.proficiency.name})")
                    if skill_summary:
                        context["skill_profile"] = skill_summary
            except Exception:
                logger.debug("Skill profile fetch failed for %s", agent.id, exc_info=True)

        # AD-488: Attention redirect after circuit breaker recovery
        redirect = self._circuit_breaker.get_attention_redirect(agent.id)
        if redirect:
            context["circuit_breaker_redirect"] = redirect

        # AD-504: Self-monitoring context
        try:
            callsign = ""
            if hasattr(rt, 'callsign_registry'):
                callsign = rt.callsign_registry.get_callsign(agent.agent_type)
            self_monitoring = await self._build_self_monitoring_context(agent, callsign, rt)
            if self_monitoring:
                context["self_monitoring"] = self_monitoring
        except Exception:
            logger.debug("Self-monitoring context failed for %s", agent.id, exc_info=True)

        # AD-471: Night Orders context for conn-holder
        if hasattr(rt, 'conn_manager') and rt.conn_manager and rt.conn_manager.is_active:
            conn_state = rt.conn_manager.state
            if conn_state.holder_agent_id == agent.id:
                # This agent holds the conn — inject Night Orders
                night_ctx: dict[str, Any] = {
                    "role": "You currently hold the conn (temporary command authority).",
                    "conn_scope": {
                        "can_approve_builds": conn_state.can_approve_builds,
                        "can_change_alert_yellow": conn_state.can_change_alert_yellow,
                        "can_issue_orders": conn_state.can_issue_orders,
                    },
                }
                if hasattr(rt, '_night_orders_mgr') and rt._night_orders_mgr and rt._night_orders_mgr.active:
                    orders = rt._night_orders_mgr.orders
                    night_ctx["night_orders"] = {
                        "template": orders.template or "custom",
                        "instructions": orders.instructions,
                        "alert_boundary": orders.alert_boundary,
                        "escalation_triggers": orders.escalation_triggers,
                        "remaining_hours": round(max(0, orders.expires_at - time.time()) / 3600, 1),
                    }
                context["conn_authority"] = night_ctx

        return context

    async def _build_self_monitoring_context(
        self,
        agent: Any,
        callsign: str,
        rt: Any,
    ) -> dict[str, Any]:
        """AD-504: Build self-monitoring context for agent self-regulation.

        Returns dict with keys: recent_posts, self_similarity, notebook_index,
        notebook_content, memory_state. All values are optional/nullable.
        Earned Agency tier controls verbosity.
        """
        result: dict[str, Any] = {}
        trust_score = rt.trust_network.get_score(agent.id) if hasattr(rt, 'trust_network') and rt.trust_network else 0.5
        rank = Rank.from_trust(trust_score)
        agency = agency_from_rank(rank)

        # Tier-based feature gating
        TIER_CONFIG = {
            AgencyLevel.REACTIVE: {"posts": 0, "notebooks": False, "similarity": False},
            AgencyLevel.SUGGESTIVE: {"posts": 3, "notebooks": False, "similarity": True},
            AgencyLevel.AUTONOMOUS: {"posts": 5, "notebooks": True, "similarity": True},
            AgencyLevel.UNRESTRICTED: {"posts": 5, "notebooks": True, "similarity": True},
        }
        tier = TIER_CONFIG.get(agency, TIER_CONFIG[AgencyLevel.SUGGESTIVE])

        # --- AD-506a: Cognitive zone awareness (before tier gating) ---
        if hasattr(self, '_circuit_breaker'):
            zone = self._circuit_breaker.get_zone(agent.id)
            if zone != "green":
                result["cognitive_zone"] = zone
                if zone == "amber":
                    result["zone_note"] = (
                        "Your recent posts show increasing similarity to each other. "
                        "This is a natural signal to pause and consider: do you have "
                        "genuinely new information to contribute, or are you circling "
                        "the same ground? If unsure, try [NO_RESPONSE] or write to "
                        "your notebook instead."
                    )
                elif zone == "red":
                    result["zone_note"] = (
                        "Your cognitive circuit breaker has activated. This is health "
                        "protection, not punishment. The Counselor has been notified. "
                        "Focus on a different aspect of operations or respond with "
                        "[NO_RESPONSE] until you have a genuinely fresh perspective."
                    )
                elif zone == "critical":
                    result["zone_note"] = (
                        "Critical cognitive state — repeated pattern loops detected. "
                        "The Captain has been notified. Extended mandatory cooldown is "
                        "in effect. When you return, deliberately choose a completely "
                        "different topic. Your previous train of thought needs rest."
                    )

        if tier["posts"] == 0:
            return result

        # --- (1) Recent output window ---
        try:
            if hasattr(rt, 'ward_room') and rt.ward_room:
                since = time.time() - 3600  # Last hour
                limit = tier["posts"]
                posts = await rt.ward_room.get_posts_by_author(callsign, limit=limit, since=since)
                if posts:
                    result["recent_posts"] = [
                        {
                            "body": p["body"][:150],
                            "age": format_duration(time.time() - p["created_at"]),
                        }
                        for p in posts
                    ]
        except Exception:
            logger.debug("Self-monitoring: failed to get recent posts for %s", callsign, exc_info=True)

        # --- (2) Self-similarity score ---
        if tier["similarity"]:
            try:
                posts_for_sim = result.get("recent_posts", [])
                if len(posts_for_sim) >= 2:
                    from probos.cognitive.similarity import jaccard_similarity, text_to_words
                    word_sets = [text_to_words(p["body"]) for p in posts_for_sim]
                    total_sim = 0.0
                    pair_count = 0
                    for j in range(len(word_sets)):
                        for k in range(j + 1, len(word_sets)):
                            total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                            pair_count += 1
                    if pair_count > 0:
                        result["self_similarity"] = round(total_sim / pair_count, 2)
            except Exception:
                logger.debug("Self-monitoring: similarity calc failed for %s", callsign, exc_info=True)

        # --- (4) Dynamic cooldown ("take a breath") ---
        sim = result.get("self_similarity", 0.0)
        if sim >= 0.5:
            current_cooldown = self.get_agent_cooldown(agent.id)
            new_cooldown = min(current_cooldown * 1.5, 1800)
            if new_cooldown > current_cooldown:
                self.set_agent_cooldown(agent.id, new_cooldown)
                result["cooldown_increased"] = True

        # AD-505: Include cooldown reason if set
        reason = self.get_cooldown_reason(agent.id)
        if reason:
            result["cooldown_reason"] = reason

        # --- (7) Memory state awareness ---
        try:
            if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
                episode_count = await rt.episodic_memory.count_for_agent(
                    getattr(agent, 'sovereign_id', agent.id)
                )
                lifecycle = getattr(rt, '_lifecycle_state', 'first_boot')
                uptime = time.time() - getattr(rt, '_start_time_wall', time.time())
                result["memory_state"] = {
                    "episode_count": episode_count,
                    "lifecycle": lifecycle,
                    "uptime_hours": round(uptime / 3600, 1),
                }
        except Exception:
            logger.debug("Self-monitoring: memory state failed for %s", callsign, exc_info=True)

        # --- (8) Notebook continuity ---
        # AD-567f: Cascade context delivered via Bridge Alerts + Counselor, not self-monitoring.
        # Verification context available as a tool agents invoke, not default injection.
        if tier["notebooks"]:
            try:
                if hasattr(rt, '_records_store') and rt._records_store:
                    entries = await rt._records_store.list_entries(
                        f"notebooks/{callsign}",
                        author=callsign,
                    )
                    if entries:
                        # AD-550: Enhanced index with content previews + recency
                        sorted_entries = sorted(
                            entries,
                            key=lambda e: e.get("frontmatter", {}).get("updated", ""),
                            reverse=True,
                        )
                        now_ts = time.time()

                        # Entry/topic counts
                        result["notebook_summary"] = {
                            "total_entries": len(entries),
                            "total_topics": len(set(
                                e.get("frontmatter", {}).get("topic", e["path"].split("/")[-1].replace(".md", ""))
                                for e in entries
                            )),
                        }

                        top5 = sorted_entries[:5]
                        enriched_index = []
                        for e in top5:
                            fm = e.get("frontmatter", {})
                            topic = fm.get("topic", e["path"].split("/")[-1].replace(".md", ""))
                            updated_str = fm.get("updated", "")

                            # Human-readable recency
                            recency = ""
                            if updated_str:
                                try:
                                    entry_ts = datetime.fromisoformat(updated_str).timestamp()
                                    delta_s = now_ts - entry_ts
                                    if delta_s < 3600:
                                        recency = f"{int(delta_s / 60)}m ago"
                                    elif delta_s < 86400:
                                        recency = f"{int(delta_s / 3600)}h ago"
                                    else:
                                        recency = f"{int(delta_s / 86400)}d ago"
                                except (ValueError, TypeError):
                                    pass

                            # Content preview (first 150 chars)
                            preview = ""
                            try:
                                entry_data = await rt._records_store.read_entry(
                                    e["path"],
                                    reader_id=callsign,
                                    reader_department=getattr(agent, 'department', ''),
                                )
                                if entry_data and entry_data.get("content"):
                                    preview = entry_data["content"][:150].replace("\n", " ").strip()
                            except Exception:
                                pass

                            enriched_index.append({
                                "topic": topic,
                                "updated": updated_str,
                                "recency": recency,
                                "preview": preview,
                                "revision": fm.get("revision", 1),  # AD-552
                            })

                        result["notebook_index"] = enriched_index

                        # AD-552: Repetition warnings for high-revision topics
                        _rep_thresh = 3
                        _rep_window_h = 48.0
                        if hasattr(rt, 'config') and hasattr(rt.config, 'records'):
                            _rep_thresh = getattr(rt.config.records, 'notebook_repetition_threshold_count', 3)
                            _rep_window_h = getattr(rt.config.records, 'notebook_repetition_window_hours', 48.0)
                        warnings = []
                        for ei in enriched_index:
                            rev = ei.get("revision", 1)
                            if rev >= _rep_thresh and ei.get("updated"):
                                try:
                                    _ei_ts = datetime.fromisoformat(ei["updated"]).timestamp()
                                    if (now_ts - _ei_ts) < (_rep_window_h * 3600):
                                        warnings.append(
                                            f"You've written about {ei['topic']} {rev} times recently. "
                                            f"Review your existing entry before writing again."
                                        )
                                except (ValueError, TypeError):
                                    pass
                        if warnings:
                            result["notebook_repetition_warnings"] = warnings

                    # Semantic pull: search notebooks for content relevant to current think
                    dept = getattr(agent, 'department', '')
                    if dept and entries:
                        search_results = await rt._records_store.search(
                            dept, scope=f"notebooks/{callsign}",
                        )
                        if search_results:
                            top = search_results[0]
                            result["notebook_content"] = {
                                "topic": top.get("path", "").split("/")[-1].replace(".md", ""),
                                "snippet": top.get("snippet", "")[:300],
                            }
            except Exception:
                logger.debug("Self-monitoring: notebook query failed for %s", callsign, exc_info=True)

            # --- Pending notebook reads from previous cycle ---
            pending_key = agent.id
            if pending_key in self._pending_notebook_reads:
                topic_slug = self._pending_notebook_reads.pop(pending_key)
                try:
                    if hasattr(rt, '_records_store') and rt._records_store:
                        entry = await rt._records_store.read_entry(
                            f"notebooks/{callsign}/{topic_slug}.md",
                            reader_id=callsign,
                            reader_department=getattr(agent, 'department', ''),
                        )
                        if entry:
                            result["notebook_content"] = {
                                "topic": topic_slug,
                                "snippet": entry.get("content", "")[:500],
                            }
                except Exception:
                    logger.debug("Self-monitoring: notebook read failed for %s/%s", callsign, topic_slug, exc_info=True)

        return result

    async def _is_similar_to_recent_posts(self, agent: Any, text: str, threshold: float = 0.5) -> bool:
        """BF-032: Check if proposed post is too similar to agent's recent Ward Room posts.

        Uses Jaccard similarity on word sets. Returns True if any recent post
        exceeds the similarity threshold.
        """
        rt = self._runtime
        if not rt or not hasattr(rt, 'ward_room') or not rt.ward_room:
            return False

        try:
            from probos.cognitive.standing_orders import get_department
            # AD-429e: Prefer ontology, fall back to legacy dict
            ont = getattr(rt, 'ontology', None)
            dept = (ont.get_agent_department(agent.agent_type) if ont else None) or get_department(agent.agent_type)
            channels = await rt.ward_room.list_channels()
            agent_posts: list[str] = []

            for ch in channels:
                try:
                    activity = await rt.ward_room.get_recent_activity(
                        ch.id, limit=10, since=None,
                    )
                    for a in activity:
                        author = a.get("author_id", "") or a.get("author", "")
                        if author == agent.id:
                            body = a.get("body", "")
                            if body:
                                agent_posts.append(body)
                except Exception:
                    logger.debug("Skipping channel", exc_info=True)
                    continue

            if not agent_posts:
                return False

            # Jaccard similarity on word sets
            new_words = set(text.lower().split())
            for post in agent_posts[:10]:  # BF-062: Check last 10 posts (was 3)
                old_words = set(post.lower().split())
                if not new_words or not old_words:
                    continue
                intersection = new_words & old_words
                union = new_words | old_words
                similarity = len(intersection) / len(union) if union else 0.0
                if similarity >= threshold:
                    return True

                # BF-062: Bigram similarity catches paraphrased near-duplicates
                new_bigrams = set(zip(text.lower().split(), text.lower().split()[1:]))
                old_bigrams = set(zip(post.lower().split(), post.lower().split()[1:]))
                if new_bigrams and old_bigrams:
                    bi_intersection = new_bigrams & old_bigrams
                    bi_union = new_bigrams | old_bigrams
                    bi_similarity = len(bi_intersection) / len(bi_union) if bi_union else 0.0
                    if bi_similarity >= threshold:
                        return True

            return False
        except Exception:
            logger.debug("Similarity check failed for %s", agent.id, exc_info=True)
            return False

    async def _extract_and_post_proposal(self, agent: Any, text: str) -> None:
        """AD-412: Extract [PROPOSAL] blocks and submit as improvement proposals."""
        import re
        pattern = r'\[PROPOSAL\]\s*\n(.*?)\n\[/PROPOSAL\]'
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return

        block = match.group(1)

        # Parse structured fields
        title = ""
        rationale = ""
        affected: list[str] = []
        priority = "medium"

        for line in block.split('\n'):
            line = line.strip()
            if line.lower().startswith("title:"):
                title = line[6:].strip()
            elif line.lower().startswith("affected systems:"):
                raw = line[17:].strip()
                affected = [s.strip() for s in raw.split(",") if s.strip()]
            elif line.lower().startswith("priority:"):
                p = line[9:].strip().lower()
                if p in ("low", "medium", "high"):
                    priority = p

        # Rationale may span multiple lines — capture everything after "Rationale:"
        # that isn't another field header
        in_rationale = False
        rationale_lines: list[str] = []
        for line in block.split('\n'):
            stripped = line.strip()
            if stripped.lower().startswith("rationale:"):
                rest = stripped[10:].strip()
                if rest:
                    rationale_lines.append(rest)
                in_rationale = True
            elif in_rationale:
                if any(stripped.lower().startswith(f) for f in ("title:", "affected systems:", "priority:")):
                    in_rationale = False
                else:
                    rationale_lines.append(stripped)
        rationale = "\n".join(rationale_lines).strip()

        if not title or not rationale:
            return  # Incomplete proposal — skip silently

        rt = self._runtime
        try:
            from probos.types import IntentMessage
            intent = IntentMessage(
                intent="propose_improvement",
                params={
                    "title": title,
                    "rationale": rationale,
                    "affected_systems": affected,
                    "priority_suggestion": priority,
                },
                context=f"Proactive proposal from {getattr(agent, 'agent_type', 'unknown')}",
            )
            if rt.ward_room_router:
                await rt.ward_room_router.handle_propose_improvement(intent, agent)
        except Exception:
            logger.debug("Failed to post improvement proposal from %s", getattr(agent, 'agent_type', 'unknown'), exc_info=True)

    async def _post_to_ward_room(self, agent: Any, text: str) -> None:
        """Create a Ward Room thread with the agent's proactive observation."""
        rt = self._runtime

        # Find agent's department channel
        from probos.cognitive.standing_orders import get_department
        # AD-429e: Prefer ontology, fall back to legacy dict
        ont = getattr(rt, 'ontology', None)
        dept = (ont.get_agent_department(agent.agent_type) if ont else None) or get_department(agent.agent_type)

        channels = await rt.ward_room.list_channels()
        target_channel = None

        if dept:
            # Prefer department channel
            for ch in channels:
                if ch.channel_type == "department" and ch.department == dept:
                    target_channel = ch
                    break

        if not target_channel:
            # Fallback to All Hands (ship-wide)
            for ch in channels:
                if ch.channel_type == "ship":
                    target_channel = ch
                    break

        if not target_channel:
            logger.debug("No target channel found for proactive post from %s", agent.agent_type)
            return

        # Get callsign
        callsign = ""
        if hasattr(rt, 'callsign_registry'):
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)

        # Truncate to first sentence/line for title, use full text as body
        title_text = text.split('\n')[0][:100]
        if len(title_text) < len(text.split('\n')[0]):
            title_text += "..."

        await rt.ward_room.create_thread(
            channel_id=target_channel.id,
            author_id=agent.id,
            title=f"[Observation] {title_text}",
            body=text,
            author_callsign=callsign or agent.agent_type,
        )

    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """AD-437: Extract structured actions from proactive response and execute them.

        Currently supports:
        - [ENDORSE post_id UP/DOWN] — endorse a Ward Room post
        - [REPLY thread_id] ... [/REPLY] — reply to an existing thread

        Actions are gated by Earned Agency tier:
        - Ensign: no actions (can't think proactively anyway)
        - Lieutenant: endorse only
        - Commander+: endorse + reply

        Returns (cleaned_text, actions_executed).
        """
        rt = self._runtime
        if not rt or not rt.ward_room:
            return text, []

        # Determine agent's action permissions
        trust_score = rt.trust_network.get_score(agent.id)
        rank = Rank.from_trust(trust_score)
        actions_executed: list[dict] = []

        # --- Endorsements (Lieutenant+) ---
        if rank.value != Rank.ENSIGN.value:
            cleaned, endorsements = rt.ward_room_router.extract_endorsements(text) if rt.ward_room_router else (text, [])
            if endorsements:
                await rt.ward_room_router.process_endorsements(endorsements, agent_id=agent.id)
                actions_executed.extend(
                    {"type": "endorse", "target": e["post_id"], "direction": e["direction"]}
                    for e in endorsements
                )
                text = cleaned

                # AD-428: Record exercise of Communication PCC
                if hasattr(rt, 'skill_service') and rt.skill_service:
                    try:
                        await rt.skill_service.record_exercise(agent.id, "communication")
                    except Exception:
                        logger.debug("Skill exercise recording failed", exc_info=True)

        # --- Replies (Lieutenant+) --- BF-061
        if rank.value != Rank.ENSIGN.value:
            text, reply_actions = await self._extract_and_execute_replies(
                agent, text
            )
            actions_executed.extend(reply_actions)

        # --- Direct Messages --- AD-453/AD-485
        # Read configurable minimum rank (default: ensign = everyone can DM)
        dm_min_rank_str = "ensign"
        if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
            dm_min_rank_str = rt.config.communications.dm_min_rank
        dm_min_rank = Rank[dm_min_rank_str.upper()] if dm_min_rank_str.upper() in Rank.__members__ else Rank.ENSIGN
        _RANK_ORDER_DM = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(dm_min_rank):
            text, dm_actions = await self._extract_and_execute_dms(agent, text)
            actions_executed.extend(dm_actions)

        # --- Notebook writes (AD-434) ---
        notebook_pattern = r'\[NOTEBOOK\s+([\w-]+)\](.*?)\[/NOTEBOOK\]'
        notebook_matches = re.findall(notebook_pattern, text, re.DOTALL)
        for topic_slug, notebook_content in notebook_matches:
            notebook_content = notebook_content.strip()
            if not notebook_content or not self._runtime._records_store:
                continue
            try:
                callsign = agent.callsign if hasattr(agent, 'callsign') else agent.agent_type
                department = ""
                if self._runtime.ontology:
                    dept = self._runtime.ontology.get_agent_department(agent.agent_type)
                    if dept:
                        department = dept.department_id if hasattr(dept, 'department_id') else str(dept)

                # AD-550: Read-before-write dedup gate
                dedup_enabled = True
                dedup_threshold = 0.8
                dedup_staleness = 72.0
                dedup_max_scan = 20
                if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
                    rc = self._runtime.config.records
                    dedup_enabled = getattr(rc, 'notebook_dedup_enabled', True)
                    dedup_threshold = getattr(rc, 'notebook_similarity_threshold', 0.8)
                    dedup_staleness = getattr(rc, 'notebook_staleness_hours', 72.0)
                    dedup_max_scan = getattr(rc, 'notebook_max_scan_entries', 20)

                if dedup_enabled:
                    try:
                        dedup_result = await self._runtime._records_store.check_notebook_similarity(
                            callsign=callsign,
                            topic_slug=topic_slug,
                            new_content=notebook_content,
                            similarity_threshold=dedup_threshold,
                            staleness_hours=dedup_staleness,
                            max_scan_entries=dedup_max_scan,
                        )
                    except Exception:
                        logger.debug("AD-550: Dedup check failed for %s/%s, writing anyway", callsign, topic_slug, exc_info=True)
                        dedup_result = {"action": "write", "reason": "dedup_check_failed", "existing_path": None, "existing_content": None, "similarity": 0.0}

                    if dedup_result["action"] == "suppress":
                        logger.info(
                            "AD-550: Notebook write suppressed for %s/%s: %s (similarity=%.2f)",
                            callsign, topic_slug, dedup_result["reason"], dedup_result["similarity"],
                        )
                        # AD-555: Record dedup suppression for quality metrics
                        _quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
                        if _quality_engine:
                            _quality_engine.record_event("dedup_suppression")
                        actions_executed.append({
                            "type": "notebook_suppressed",
                            "topic": topic_slug,
                            "callsign": callsign,
                            "reason": dedup_result["reason"],
                        })
                        continue  # Skip this notebook block

                    # AD-552: Cumulative frequency check for self-repetition
                    rep_enabled = True
                    rep_window = 48.0
                    rep_threshold = 3
                    rep_novelty = 0.2
                    rep_suppress_count = 5
                    if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
                        rc2 = self._runtime.config.records
                        rep_enabled = getattr(rc2, 'notebook_repetition_enabled', True)
                        rep_window = getattr(rc2, 'notebook_repetition_window_hours', 48.0)
                        rep_threshold = getattr(rc2, 'notebook_repetition_threshold_count', 3)
                        rep_novelty = getattr(rc2, 'notebook_repetition_novelty_threshold', 0.2)
                        rep_suppress_count = getattr(rc2, 'notebook_repetition_suppression_count', 5)

                    if rep_enabled:
                        try:
                            _rev = dedup_result.get("revision", 0)
                            _created_iso = dedup_result.get("created_iso")
                            if _rev >= rep_threshold and _created_iso:
                                _created_ts = datetime.fromisoformat(_created_iso).timestamp()
                                _hours_active = (time.time() - _created_ts) / 3600.0
                                if _hours_active < rep_window:
                                    _novelty = 1.0 - dedup_result.get("similarity", 0.0)
                                    _suppressed = False

                                    # Suppress: high revision + low novelty
                                    if _rev >= rep_suppress_count and _novelty < rep_novelty:
                                        _suppressed = True
                                        logger.info(
                                            "AD-552: Suppressing write — %s has written %s %d times in %.1fh with <%.0f%% novel content",
                                            callsign, topic_slug, _rev, _hours_active, rep_novelty * 100,
                                        )
                                        dedup_result["action"] = "suppress"

                                    # Emit event for detection (any revision over threshold in window)
                                    if _novelty < rep_novelty or (_rev >= rep_suppress_count and _novelty < 0.3):
                                        logger.info(
                                            "AD-552: Self-repetition detected for %s on %s (revision=%d, hours_active=%.1f, novelty=%.2f)",
                                            callsign, topic_slug, _rev, _hours_active, _novelty,
                                        )
                                        if hasattr(self._runtime, '_emit_event'):
                                            from probos.events import NotebookSelfRepetitionEvent
                                            evt = NotebookSelfRepetitionEvent(
                                                agent_id=agent.id,
                                                agent_callsign=callsign,
                                                topic_slug=topic_slug,
                                                revision=_rev,
                                                hours_active=round(_hours_active, 1),
                                                novelty=round(_novelty, 2),
                                                suppressed=_suppressed,
                                            )
                                            try:
                                                await self._runtime._emit_event(evt.to_dict())
                                            except Exception:
                                                logger.debug("AD-552: Event emission failed", exc_info=True)
                                        # AD-555: Record repetition alert for quality metrics
                                        _quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
                                        if _quality_engine:
                                            _quality_engine.record_event("repetition_alert", callsign=callsign)

                                    if _suppressed:
                                        actions_executed.append({
                                            "type": "notebook_suppressed",
                                            "topic": topic_slug,
                                            "callsign": callsign,
                                            "reason": "self_repetition_suppressed",
                                        })
                                        continue  # Skip this notebook block
                        except Exception:
                            logger.debug("AD-552: Frequency check failed for %s/%s", callsign, topic_slug, exc_info=True)

                # AD-553: Collect metrics snapshot and compute delta
                _nb_metrics: dict[str, Any] = {}
                _metric_capture_enabled = True
                if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
                    _metric_capture_enabled = getattr(
                        self._runtime.config.records, 'notebook_metrics_enabled', True
                    )

                if _metric_capture_enabled:
                    try:
                        _nb_metrics = collect_notebook_metrics(self._runtime, agent.id)
                        # Baseline delta: compare with previous metrics if updating
                        if dedup_result.get("action") == "update":
                            _old_metrics = dedup_result.get("existing_metrics", {})
                            if _old_metrics and _nb_metrics:
                                _nb_metrics_delta = compute_metrics_delta(_old_metrics, _nb_metrics)
                                if _nb_metrics_delta:
                                    _nb_metrics["metrics_delta"] = _nb_metrics_delta
                    except Exception:
                        logger.debug("AD-553: Metric collection failed for %s/%s", callsign, topic_slug, exc_info=True)

                await self._runtime._records_store.write_notebook(
                    callsign=callsign,
                    topic_slug=topic_slug,
                    content=notebook_content,
                    department=department,
                    tags=[topic_slug],
                    metrics=_nb_metrics if _nb_metrics else None,  # AD-553
                )
                actions_executed.append({
                    "type": "notebook_write",
                    "topic": topic_slug,
                    "callsign": callsign,
                })
                # AD-555: Record successful write for quality metrics
                _quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
                if _quality_engine:
                    _quality_engine.record_event("dedup_write")
                logger.info("Notebook entry written: %s/%s", callsign, topic_slug)

                # AD-554: Real-time cross-agent convergence/divergence detection
                _conv_enabled = True
                if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
                    _conv_enabled = getattr(
                        self._runtime.config.records, 'realtime_convergence_enabled', True
                    )

                if _conv_enabled and department:
                    try:
                        _rc554 = getattr(self._runtime.config, 'records', None) if hasattr(self._runtime, 'config') else None
                        conv_result = await self._runtime._records_store.check_cross_agent_convergence(
                            anchor_callsign=callsign,
                            anchor_department=department,
                            anchor_topic_slug=topic_slug,
                            anchor_content=notebook_content,
                            convergence_threshold=getattr(_rc554, 'realtime_convergence_threshold', 0.5) if _rc554 else 0.5,
                            divergence_threshold=getattr(_rc554, 'realtime_divergence_threshold', 0.3) if _rc554 else 0.3,
                            staleness_hours=getattr(_rc554, 'realtime_convergence_staleness_hours', 72.0) if _rc554 else 72.0,
                            max_scan_per_agent=getattr(_rc554, 'realtime_max_scan_per_agent', 5) if _rc554 else 5,
                            min_convergence_agents=getattr(_rc554, 'realtime_min_convergence_agents', 2) if _rc554 else 2,
                            min_convergence_departments=getattr(_rc554, 'realtime_min_convergence_departments', 2) if _rc554 else 2,
                        )

                        if conv_result.get("convergence_detected"):
                            # 1. Auto-generate convergence report
                            report_path = await self._write_convergence_report(
                                conv_result, callsign, topic_slug,
                            )
                            conv_result["report_path"] = report_path or ""

                            # 2. Emit typed event
                            if hasattr(self._runtime, '_emit_event'):
                                from probos.events import ConvergenceDetectedEvent
                                evt = ConvergenceDetectedEvent(
                                    agents=conv_result["convergence_agents"],
                                    departments=conv_result["convergence_departments"],
                                    topic=conv_result.get("convergence_topic", topic_slug),
                                    coherence=conv_result.get("convergence_coherence", 0.0),
                                    source="realtime",
                                    report_path=conv_result.get("report_path", ""),
                                )
                                try:
                                    await self._runtime._emit_event(evt.to_dict())
                                except Exception:
                                    logger.debug("AD-554: Convergence event emission failed", exc_info=True)

                            # 3. Bridge Alert
                            await self._emit_convergence_bridge_alert(conv_result)

                            # AD-555: Record convergence for quality metrics
                            _quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
                            if _quality_engine:
                                _quality_engine.record_event(
                                    "convergence",
                                    agents=conv_result.get("convergence_agents", []),
                                )

                            logger.info(
                                "AD-554: Real-time convergence detected! %d agents from %d depts on %s",
                                len(conv_result["convergence_agents"]),
                                len(conv_result["convergence_departments"]),
                                conv_result.get("convergence_topic", topic_slug),
                            )

                        if conv_result.get("divergence_detected"):
                            # 1. Emit typed event
                            if hasattr(self._runtime, '_emit_event'):
                                from probos.events import DivergenceDetectedEvent
                                evt = DivergenceDetectedEvent(
                                    agents=conv_result["divergence_agents"],
                                    departments=conv_result["divergence_departments"],
                                    topic=conv_result.get("divergence_topic", topic_slug),
                                    similarity=conv_result.get("divergence_similarity", 0.0),
                                )
                                try:
                                    await self._runtime._emit_event(evt.to_dict())
                                except Exception:
                                    logger.debug("AD-554: Divergence event emission failed", exc_info=True)

                            # 2. Bridge Alert
                            await self._emit_divergence_bridge_alert(conv_result)

                            # AD-555: Record divergence for quality metrics
                            _quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
                            if _quality_engine:
                                _quality_engine.record_event("divergence")

                            logger.info(
                                "AD-554: Divergence detected! %s on %s (similarity=%.2f)",
                                ", ".join(conv_result["divergence_agents"]),
                                conv_result.get("divergence_topic", topic_slug),
                                conv_result.get("divergence_similarity", 0.0),
                            )

                    except Exception:
                        logger.debug("AD-554: Cross-agent scan failed for %s/%s", callsign, topic_slug, exc_info=True)
            except Exception as e:
                logger.warning("Notebook write failed for %s: %s", topic_slug, e)

        # BF-060: Strip ALL notebook blocks from text using regex (not string replace)
        # text.replace() failed because .strip() on captured content caused whitespace mismatch
        text = re.sub(notebook_pattern, '', text, flags=re.DOTALL).strip()

        # AD-504: [READ_NOTEBOOK topic-slug] — queue for next cycle injection
        read_nb_pattern = r'\[READ_NOTEBOOK\s+([\w-]+)\]'
        for match in re.finditer(read_nb_pattern, text):
            topic_slug = match.group(1)
            self._pending_notebook_reads[agent.id] = topic_slug
            logger.debug("Queued notebook read for %s: %s",
                        getattr(agent, 'callsign', agent.agent_type), topic_slug)
        text = re.sub(read_nb_pattern, '', text).strip()

        # AD-526a: Recreation actions — rank-gated via config
        rec_min_rank_str = "ensign"
        if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
            rec_min_rank_str = rt.config.communications.recreation_min_rank
        rec_min_rank = Rank[rec_min_rank_str.upper()] if rec_min_rank_str.upper() in Rank.__members__ else Rank.ENSIGN
        _RANK_ORDER_REC = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        if _RANK_ORDER_REC.index(rank) >= _RANK_ORDER_REC.index(rec_min_rank):
            # AD-526a: [CHALLENGE @callsign game_type] — challenge another crew member to a game
            challenge_pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
            for match in re.finditer(challenge_pattern, text):
                target_callsign = match.group(1)
                game_type = match.group(2)
                try:
                    rec_svc = getattr(rt, 'recreation_service', None)
                    if rec_svc:
                        # Resolve target callsign to agent
                        target_agent = None
                        if hasattr(rt, 'callsign_registry'):
                            target_agent = rt.callsign_registry.resolve(target_callsign)
                        if not target_agent:
                            logger.debug("AD-526a: Target callsign %s not found", target_callsign)
                            continue
                        # Create game in Recreation channel thread
                        rec_ch = None
                        if rt.ward_room:
                            channels = await rt.ward_room.list_channels()
                            rec_ch = next((c for c in channels if c.name == "Recreation"), None)
                        thread_id = ""
                        if rec_ch and rt.ward_room:
                            thread = await rt.ward_room.post_message(
                                channel_id=rec_ch.id,
                                author_id=agent.id,
                                title=f"[Challenge] {callsign} challenges {target_callsign} to {game_type}!",
                                body=f"{callsign} has challenged {target_callsign} to a game of {game_type}! Reply to accept.",
                                author_callsign=callsign,
                            )
                            thread_id = thread.get("thread_id", "") if isinstance(thread, dict) else ""
                        game_info = await rec_svc.create_game(
                            game_type=game_type,
                            challenger=callsign,
                            opponent=target_callsign,
                            thread_id=thread_id,
                        )
                        actions_executed.append({
                            "action": "challenge",
                            "target": target_callsign,
                            "game_type": game_type,
                            "game_id": game_info["game_id"],
                        })
                        logger.info("AD-526a: %s challenged %s to %s (game %s)",
                                    callsign, target_callsign, game_type, game_info["game_id"])
                except Exception as e:
                    logger.warning("AD-526a: CHALLENGE failed for %s: %s", callsign, e)
            text = re.sub(challenge_pattern, '', text).strip()

            # AD-526a: [MOVE position] — make a move in an active game
            move_pattern = r'\[MOVE\s+(\S+)\]'
            for match in re.finditer(move_pattern, text):
                position = match.group(1)
                try:
                    rec_svc = getattr(rt, 'recreation_service', None)
                    if rec_svc:
                        # Find active game for this player
                        active_games = rec_svc.get_active_games()
                        player_game = None
                        for g in active_games:
                            state = g.get("state", {})
                            if state.get("current_player") == callsign:
                                player_game = g
                                break
                        if player_game:
                            game_info = await rec_svc.make_move(
                                game_id=player_game["game_id"],
                                player=callsign,
                                move=position,
                            )
                            actions_executed.append({
                                "action": "game_move",
                                "game_id": player_game["game_id"],
                                "move": position,
                            })
                            # Post board update to Recreation channel
                            if rt.ward_room and player_game.get("thread_id"):
                                board = rec_svc.render_board(player_game["game_id"]) if not game_info.get("result") else ""
                                result = game_info.get("result")
                                if result:
                                    status = result.get("status", "")
                                    winner = result.get("winner", "")
                                    body = f"Game over! {'Winner: ' + winner if winner else 'Draw!'}"
                                else:
                                    body = f"```\n{board}\n```\nNext: {game_info['state']['current_player']}"
                                try:
                                    await rt.ward_room.reply_to_thread(
                                        thread_id=player_game["thread_id"],
                                        author_id=agent.id,
                                        body=body,
                                        author_callsign=callsign,
                                    )
                                except Exception:
                                    logger.debug("AD-526a: Board update post failed", exc_info=True)
                        else:
                            logger.debug("AD-526a: No active game for %s", callsign)
                except Exception as e:
                    logger.warning("AD-526a: MOVE failed for %s: %s", callsign, e)
            text = re.sub(move_pattern, '', text).strip()

        return text, actions_executed

    async def _write_convergence_report(
        self, conv_result: dict, anchor_callsign: str, topic_slug: str,
    ) -> str | None:
        """AD-554: Auto-generate a convergence report in Ship's Records."""
        try:
            from uuid import uuid4 as _uuid4
            ts_slug = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            uid = str(_uuid4())[:8]
            report_path = f"reports/convergence/convergence-{ts_slug}-{uid}.md"

            agents = conv_result.get("convergence_agents", [])
            departments = conv_result.get("convergence_departments", [])
            coherence = conv_result.get("convergence_coherence", 0.0)
            topic = conv_result.get("convergence_topic", topic_slug)

            # Build perspectives from match data
            perspectives = ""
            matches = conv_result.get("convergence_matches", [])
            for m in matches:
                cs = m.get("callsign", "unknown")
                dept = m.get("department", "unknown")
                path = m.get("path", "")
                # Read content for the perspective
                snippet = ""
                if path and hasattr(self._runtime, '_records_store'):
                    try:
                        entry = await self._runtime._records_store.read_entry(
                            path, reader_id="system", reader_department="",
                        )
                        if entry:
                            snippet = entry.get("content", "")[:300].strip()
                    except Exception:
                        pass
                perspectives += f"\n### {cs} ({dept})\n\n{snippet}\n"

            report_content = (
                f"## Real-Time Convergence Report\n\n"
                f"**Detected:** {datetime.utcnow().isoformat()}Z\n\n"
                f"**Source:** Real-time notebook monitor\n\n"
                f"**Topic:** {topic}\n\n"
                f"**Agents:** {', '.join(sorted(agents))}\n\n"
                f"**Departments:** {', '.join(sorted(departments))}\n\n"
                f"**Coherence:** {coherence:.3f}\n\n"
                f"## Contributing Perspectives\n{perspectives}\n"
            )

            await self._runtime._records_store.write_entry(
                author="system",
                path=report_path,
                content=report_content,
                message=f"AD-554: Real-time convergence report ({topic})",
                classification="ship",
                tags=["convergence", "ad-554", "realtime"],
            )
            return report_path
        except Exception:
            logger.debug("AD-554: Failed to write convergence report", exc_info=True)
            return None

    async def _emit_convergence_bridge_alert(self, conv_result: dict) -> None:
        """AD-554: Create and deliver a convergence BridgeAlert."""
        ba_svc = getattr(self._runtime, '_bridge_alerts', None)
        deliver_fn = getattr(self._runtime, '_deliver_bridge_alert', None)
        if not ba_svc or not deliver_fn:
            return

        alerts = ba_svc.check_realtime_convergence(conv_result)
        for alert in alerts:
            try:
                await deliver_fn(alert)
            except Exception:
                logger.debug("AD-554: Bridge alert delivery failed", exc_info=True)

    async def _emit_divergence_bridge_alert(self, conv_result: dict) -> None:
        """AD-554: Create and deliver a divergence BridgeAlert."""
        ba_svc = getattr(self._runtime, '_bridge_alerts', None)
        deliver_fn = getattr(self._runtime, '_deliver_bridge_alert', None)
        if not ba_svc or not deliver_fn:
            return

        alerts = ba_svc.check_divergence(conv_result)
        for alert in alerts:
            try:
                await deliver_fn(alert)
            except Exception:
                logger.debug("AD-554: Divergence bridge alert delivery failed", exc_info=True)

    async def _resolve_thread_id(self, thread_id: str) -> str | None:
        """BF-061: Resolve a full or partial thread ID to an actual thread ID."""
        rt = self._runtime
        # Try exact match first
        thread = await rt.ward_room.get_thread(thread_id)
        if thread:
            return thread_id
        # Try prefix match on recent threads across channels
        if len(thread_id) < 36:
            channels = await rt.ward_room.list_channels()
            for ch in channels:
                try:
                    activity = await rt.ward_room.get_recent_activity(ch.id, limit=20, since=None)
                    for item in activity:
                        tid = item.get("thread_id", "") or item.get("id", "")
                        if tid and tid.startswith(thread_id):
                            return tid
                except Exception:
                    logger.debug("Skipping channel", exc_info=True)
                    continue
        return None

    async def _extract_and_execute_replies(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """AD-437: Extract [REPLY thread_id]...[/REPLY] blocks and post as replies.

        Allows Lieutenant+ agents to reply to existing threads instead of
        always creating new threads for every observation.
        """
        import re
        rt = self._runtime
        actions: list[dict] = []

        # BF-061: More flexible pattern — optional thread: prefix, no mandatory newline
        pattern = re.compile(
            r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
            re.DOTALL | re.IGNORECASE,
        )

        for match in pattern.finditer(text):
            thread_id = match.group(1)
            reply_body = match.group(2).strip()
            if not reply_body:
                continue

            try:
                # BF-061: Resolve thread ID (may be partial or prefixed)
                resolved_id = await self._resolve_thread_id(thread_id)
                if not resolved_id:
                    logger.debug("AD-437: Reply target thread %s not found", thread_id)
                    continue
                thread_id = resolved_id
                thread = await rt.ward_room.get_thread(thread_id)

                # Check thread isn't locked
                thread_data = thread.get("thread", thread)
                if thread_data.get("locked"):
                    logger.debug("AD-437: Reply target thread %s is locked", thread_id)
                    continue

                # BF-105: Self-similarity guard for replies (mirrors BF-032 for new threads)
                if await self._is_similar_to_recent_posts(agent, reply_body):
                    logger.debug(
                        "BF-105: Suppressed similar reply from %s to thread %s",
                        agent.agent_type, thread_id[:8],
                    )
                    continue

                # Get callsign
                callsign = ""
                if hasattr(rt, 'callsign_registry'):
                    callsign = rt.callsign_registry.get_callsign(agent.agent_type)

                await rt.ward_room.create_post(
                    thread_id=thread_id,
                    author_id=agent.id,
                    body=reply_body,
                    author_callsign=callsign or agent.agent_type,
                )
                actions.append({
                    "type": "reply",
                    "thread_id": thread_id,
                    "length": len(reply_body),
                })
                logger.debug(
                    "AD-437: %s replied to thread %s (%d chars)",
                    agent.agent_type, thread_id, len(reply_body),
                )
            except Exception:
                logger.debug(
                    "AD-437: Reply to thread %s failed for %s",
                    thread_id, agent.agent_type, exc_info=True,
                )

        # Strip all [REPLY]...[/REPLY] blocks from text
        cleaned = pattern.sub('', text).strip()
        return cleaned, actions

    async def _extract_and_execute_dms(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """AD-453: Extract [DM @callsign]...[/DM] blocks and send as DMs."""
        import re
        rt = self._runtime
        actions: list[dict] = []

        pattern = re.compile(
            r'\[DM\s+@?(\S+)\]\s*\n(.*?)\n\[/DM\]',
            re.DOTALL | re.IGNORECASE,
        )

        for match in pattern.finditer(text):
            target_callsign = match.group(1)
            dm_body = match.group(2).strip()
            if not dm_body:
                continue

            # AD-485: Special case — DM to Captain
            if target_callsign.lower() == "captain":
                try:
                    sender_callsign = ""
                    if hasattr(rt, 'callsign_registry'):
                        sender_callsign = rt.callsign_registry.get_callsign(agent.agent_type)

                    captain_channel_name = f"dm-captain-{agent.id[:8]}"
                    dm_channel = None
                    channels = await rt.ward_room.list_channels()
                    for ch in channels:
                        if ch.name == captain_channel_name and ch.channel_type == "dm":
                            dm_channel = ch
                            break
                    if not dm_channel:
                        dm_channel = await rt.ward_room.create_channel(
                            name=captain_channel_name,
                            description=f"DM: {sender_callsign or agent.agent_type} → Captain",
                            channel_type="dm",
                            created_by=agent.id,
                        )

                    await rt.ward_room.create_thread(
                        channel_id=dm_channel.id,
                        author_id=agent.id,
                        title=f"[DM to Captain from @{sender_callsign or agent.agent_type}]",
                        body=dm_body,
                        author_callsign=sender_callsign or agent.agent_type,
                    )

                    actions.append({"type": "dm", "target_callsign": "captain", "target_agent_id": "captain"})
                    logger.info("AD-485: %s sent DM to Captain", sender_callsign or agent.agent_type)
                except Exception as e:
                    logger.warning("AD-485: DM to Captain failed: %s", e)
                continue

            # Resolve callsign to agent_type
            target_agent_type = None
            if hasattr(rt, 'callsign_registry'):
                resolved = rt.callsign_registry.resolve(target_callsign)
                if resolved:
                    target_agent_type = resolved.get("agent_type")
            if not target_agent_type:
                logger.debug("AD-453: DM target @%s not found in registry", target_callsign)
                continue

            # Don't DM yourself
            if target_agent_type == agent.agent_type or target_agent_type == agent.id:
                continue

            # Resolve target's full agent ID
            target_full_id = None
            for a in rt.registry.all():
                if a.agent_type == target_agent_type:
                    target_full_id = a.id
                    break
            if not target_full_id:
                continue

            try:
                sender_callsign = ""
                if hasattr(rt, 'callsign_registry'):
                    sender_callsign = rt.callsign_registry.get_callsign(agent.agent_type)

                dm_channel = await rt.ward_room.get_or_create_dm_channel(
                    agent.id, target_full_id,
                    callsign_a=sender_callsign or agent.agent_type,
                    callsign_b=target_callsign,
                )

                await rt.ward_room.create_thread(
                    channel_id=dm_channel.id,
                    author_id=agent.id,
                    title=f"[DM to @{target_callsign}]",
                    body=dm_body,
                    author_callsign=sender_callsign or agent.agent_type,
                )

                actions.append({
                    "type": "dm",
                    "target_callsign": target_callsign,
                    "target_agent_id": target_full_id,
                })
                logger.info("AD-453: %s sent DM to @%s", sender_callsign or agent.agent_type, target_callsign)

                # Record Hebbian social connection
                if hasattr(rt, 'hebbian_router') and rt.hebbian_router:
                    from probos.mesh.routing import REL_SOCIAL
                    rt.hebbian_router.record_interaction(
                        source=agent.id, target=target_full_id,
                        success=True, rel_type=REL_SOCIAL,
                    )
                    rt._emit_event(EventType.HEBBIAN_UPDATE, {
                        "source": agent.id, "target": target_full_id,
                        "weight": format_trust(rt.hebbian_router.get_weight(agent.id, target_full_id)),
                        "rel_type": "social",
                    })
            except Exception as e:
                logger.warning("AD-453: DM to @%s failed: %s", target_callsign, e)

        cleaned = pattern.sub('', text).strip()
        return cleaned, actions

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    def set_knowledge_store(self, store) -> None:
        """Inject knowledge store for cooldown persistence."""
        self._knowledge_store = store

    def get_cooldowns(self) -> dict:
        """Return a copy of per-agent cooldown data for persistence."""
        return dict(self._agent_cooldowns)

    @property
    def llm_failure_count(self) -> int:
        """BF-069: Number of consecutive proactive loop failures."""
        return self._llm_failure_count
