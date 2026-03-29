"""Proactive Cognitive Loop — periodic idle-think for crew agents (Phase 28b)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable

from probos.crew_profile import Rank
from probos.duty_schedule import DutyScheduleTracker
from probos.earned_agency import agency_from_rank, can_think_proactively
from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
from probos.types import IntentMessage
from probos.utils import format_duration

logger = logging.getLogger(__name__)


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
        self._knowledge_store: Any = None  # AD-415: Set by runtime for persistence
        self._task: asyncio.Task | None = None
        self._runtime: Any = None  # Set via set_runtime()
        self._started_at: float = time.monotonic()  # BF-039: cold-start reference
        self._config: Any = None   # Set via set_config()
        self._duty_tracker: DutyScheduleTracker | None = None
        self._circuit_breaker = CognitiveCircuitBreaker()

    def set_runtime(self, runtime: Any) -> None:
        """Wire the runtime reference (provides registry, trust, WR, memory, etc.)."""
        self._runtime = runtime

    def set_config(self, config: Any) -> None:
        """Store ProactiveCognitiveConfig for trust signal weights (AD-414)."""
        self._config = config

    @property
    def circuit_breaker(self) -> CognitiveCircuitBreaker:
        """Expose circuit breaker for runtime wiring and API access."""
        return self._circuit_breaker

    @property
    def _default_cooldown(self) -> float:
        return self._cooldown

    def set_duty_schedule(self, config: Any) -> None:
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

    def set_agent_cooldown(self, agent_id: str, cooldown: float) -> None:
        """Set per-agent proactive cooldown override. Clamp to [60, 1800]."""
        cooldown = max(60.0, min(1800.0, cooldown))
        self._agent_cooldowns[agent_id] = cooldown
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
            if not rt._is_crew_agent(agent):
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
            pass  # Non-critical

        intent = IntentMessage(
            intent="proactive_think",
            params={
                "context_parts": context_parts,
                "trust_score": round(trust_score, 4),
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
                    from probos.types import Episode
                    callsign = ""
                    if hasattr(rt, 'callsign_registry'):
                        callsign = rt.callsign_registry.get_callsign(agent.agent_type)
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
                    "type": "bridge_alert",
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
                if self._on_event:
                    self._on_event({
                        "type": "trust_update",
                        "data": {
                            "agent_id": agent.id,
                            "agent_type": getattr(agent, "agent_type", "unknown"),
                            "new_score": new_score,
                            "weight": trust_weight,
                            "source": "proactive",
                            "duty_id": duty.duty_id if duty else None,
                        },
                    })

        # Record duty execution after successful post
        if duty and self._duty_tracker:
            self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)

        # AD-430a: Store proactive thought as episodic memory
        # BF-039: Skip if posted to Ward Room — WR creates its own episode,
        # storing here too would be a duplicate.
        wr_available = hasattr(rt, 'ward_room') and rt.ward_room
        if not wr_available and hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                from probos.types import Episode
                callsign = ""
                if hasattr(rt, 'callsign_registry'):
                    callsign = rt.callsign_registry.get_callsign(agent.agent_type)
                thought_summary = response_text[:200]
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
                )
                from probos.cognitive.episodic import EpisodicMemory
                if EpisodicMemory.should_store(episode):
                    await rt.episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store proactive thought episode for %s", agent.agent_type, exc_info=True)

        if self._on_event:
            self._on_event({
                "type": "proactive_thought",
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
        if hasattr(rt, 'is_cold_start') and rt.is_cold_start:
            context["system_note"] = (
                "SYSTEM NOTE: This is a fresh start after a system reset. "
                "All trust scores are at baseline (0.5). This is normal initialization, "
                "not a demotion. Build trust through demonstrated competence. "
                "You have no prior episodic memories — do not reference or invent past experiences."
            )

        # 1. Recent episodic memories (sovereign — only this agent's experiences)
        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                _agent_mem_id = getattr(agent, 'sovereign_id', None) or agent.id  # AD-441
                episodes = await rt.episodic_memory.recall_for_agent(
                    _agent_mem_id, "recent activity", k=5
                )
                # BF-028: Fallback to recent episodes when semantic recall misses
                if not episodes and hasattr(rt.episodic_memory, 'recent_for_agent'):
                    episodes = await rt.episodic_memory.recent_for_agent(_agent_mem_id, k=5)
                if episodes:
                    # AD-502: Include relative timestamps on recalled memories
                    include_ts = True
                    if hasattr(rt, 'config') and hasattr(rt.config, 'temporal'):
                        include_ts = rt.config.temporal.include_episode_timestamps

                    context["recent_memories"] = [
                        {
                            "input": (ep.user_input[:500] + " [trimmed]") if ep.user_input and len(ep.user_input) > 500 else (ep.user_input or ""),
                            "reflection": (ep.reflection[:500] + " [trimmed]") if ep.reflection and len(ep.reflection) > 500 else (ep.reflection or ""),
                            **({"age": format_duration(time.time() - ep.timestamp)}
                               if include_ts and ep.timestamp > 0 else {}),
                        }
                        for ep in episodes
                    ]
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
                                    "body": a.get("title", a.get("body", ""))[:150],
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
                                pass  # Non-critical

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
                                    "body": item.get("body", "")[:150],
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
                                pass  # Non-critical
            except Exception:
                logger.debug("Ward Room context fetch failed for %s", agent.id, exc_info=True)

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
            await rt._handle_propose_improvement(intent, agent)
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
            cleaned, endorsements = rt._extract_endorsements(text)
            if endorsements:
                await rt._process_endorsements(endorsements, agent.id)
                actions_executed.extend(
                    {"type": "endorse", "target": e["post_id"], "direction": e["direction"]}
                    for e in endorsements
                )
                text = cleaned

                # AD-428: Record exercise of Communication PCC
                if hasattr(rt, 'skill_service') and rt.skill_service:
                    try:
                        rt.skill_service.record_exercise(agent.id, "communication")
                    except Exception:
                        pass  # best-effort

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
                await self._runtime._records_store.write_notebook(
                    callsign=callsign,
                    topic_slug=topic_slug,
                    content=notebook_content,
                    department=department,
                    tags=[topic_slug],
                )
                actions_executed.append({
                    "type": "notebook_write",
                    "topic": topic_slug,
                    "callsign": callsign,
                })
                logger.info("Notebook entry written: %s/%s", callsign, topic_slug)
            except Exception as e:
                logger.warning("Notebook write failed for %s: %s", topic_slug, e)

        # BF-060: Strip ALL notebook blocks from text using regex (not string replace)
        # text.replace() failed because .strip() on captured content caused whitespace mismatch
        text = re.sub(notebook_pattern, '', text, flags=re.DOTALL).strip()

        return text, actions_executed

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
            for a in rt._agents:
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
                    rt._emit_event("hebbian_update", {
                        "source": agent.id, "target": target_full_id,
                        "weight": round(rt.hebbian_router.get_weight(agent.id, target_full_id), 4),
                        "rel_type": "social",
                    })
            except Exception as e:
                logger.warning("AD-453: DM to @%s failed: %s", target_callsign, e)

        cleaned = pattern.sub('', text).strip()
        return cleaned, actions
