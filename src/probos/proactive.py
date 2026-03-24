"""Proactive Cognitive Loop — periodic idle-think for crew agents (Phase 28b)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from probos.crew_profile import Rank
from probos.earned_agency import agency_from_rank, can_think_proactively
from probos.types import IntentMessage

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
        self._task: asyncio.Task | None = None
        self._runtime: Any = None  # Set via set_runtime()

    def set_runtime(self, runtime: Any) -> None:
        """Wire the runtime reference (provides registry, trust, WR, memory, etc.)."""
        self._runtime = runtime

    def get_agent_cooldown(self, agent_id: str) -> float:
        """Get effective cooldown for an agent (override or global default)."""
        return self._agent_cooldowns.get(agent_id, self._cooldown)

    def set_agent_cooldown(self, agent_id: str, cooldown: float) -> None:
        """Set per-agent proactive cooldown override. Clamp to [60, 1800]."""
        cooldown = max(60.0, min(1800.0, cooldown))
        self._agent_cooldowns[agent_id] = cooldown

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
            if time.monotonic() - last < self.get_agent_cooldown(agent.id):
                continue

            try:
                await self._think_for_agent(agent, rank, trust_score)
            except Exception:
                logger.debug(
                    "Proactive think failed for %s (fail-open)", agent.agent_type,
                    exc_info=True,
                )

    async def _think_for_agent(self, agent: Any, rank: Rank, trust_score: float) -> None:
        """Gather context, send proactive_think intent, post result if meaningful."""
        rt = self._runtime
        context_parts = await self._gather_context(agent, trust_score)

        intent = IntentMessage(
            intent="proactive_think",
            params={
                "context_parts": context_parts,
                "trust_score": round(trust_score, 4),
                "agency_level": agency_from_rank(rank).value,
                "agent_type": agent.agent_type,
            },
            target_agent_id=agent.id,
        )

        result = await agent.handle_intent(intent)

        if not result or not result.success or not result.result:
            return

        response_text = str(result.result).strip()
        if not response_text or "[NO_RESPONSE]" in response_text:
            return

        # Post to Ward Room — find agent's department channel
        await self._post_to_ward_room(agent, response_text)
        self._last_proactive[agent.id] = time.monotonic()

        if self._on_event:
            self._on_event({
                "type": "proactive_thought",
                "data": {
                    "agent_id": agent.id,
                    "agent_type": agent.agent_type,
                    "response_length": len(response_text),
                },
            })

        logger.info(
            "Proactive thought from %s (%s): %d chars",
            agent.agent_type, rank.value, len(response_text),
        )

    async def _gather_context(self, agent: Any, trust_score: float) -> dict:
        """Gather recent context for the agent's proactive review."""
        rt = self._runtime
        context: dict[str, Any] = {}

        # 1. Recent episodic memories (sovereign — only this agent's experiences)
        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                episodes = await rt.episodic_memory.recall_for_agent(
                    agent.id, "recent activity", k=5
                )
                if episodes:
                    context["recent_memories"] = [
                        {
                            "input": ep.user_input[:200] if ep.user_input else "",
                            "reflection": ep.reflection[:200] if ep.reflection else "",
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

        return context

    async def _post_to_ward_room(self, agent: Any, text: str) -> None:
        """Create a Ward Room thread with the agent's proactive observation."""
        rt = self._runtime

        # Find agent's department channel
        from probos.cognitive.standing_orders import get_department
        dept = get_department(agent.agent_type)

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
