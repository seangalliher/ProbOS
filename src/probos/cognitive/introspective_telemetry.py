"""AD-588: Introspective Telemetry Service — Queryable agent self-knowledge.

Stateless service that queries existing runtime services to assemble
telemetry snapshots for agent self-referential grounding. Part of the
Metacognitive Architecture wave (AD-587 static → AD-588 dynamic → AD-589
faithfulness verification).

Theoretical basis: Nisbett & Wilson (1977) — fix confabulation by providing
actual data, not by suppressing narratives. Agents can't introspect their
own cognitive architecture, but they CAN read their own telemetry.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class IntrospectiveTelemetryService:
    """AD-588: Queryable interface for agent self-knowledge grounded in actual telemetry."""

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    def _resolve_agent(self, agent_id: str) -> Any:
        """Resolve agent object from registry by ID."""
        rt = self._runtime
        if hasattr(rt, 'registry') and rt.registry:
            return rt.registry.get(agent_id)
        return None

    async def get_memory_state(self, agent_id: str) -> dict[str, Any]:
        """Episode count, lifecycle, retrieval mechanism, capacity."""
        result: dict[str, Any] = {}
        rt = self._runtime
        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                result["episode_count"] = await rt.episodic_memory.count_for_agent(agent_id)
            except Exception:
                result["episode_count"] = "unknown"
        result["retrieval"] = "cosine_similarity"
        result["capacity"] = "unbounded"
        result["offline_processing"] = False
        # Lifecycle
        result["lifecycle"] = getattr(rt, '_lifecycle_state', 'unknown')
        return result

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]:
        """Score, observations, uncertainty, recent trend, trust model."""
        result: dict[str, Any] = {}
        rt = self._runtime
        if hasattr(rt, 'trust_network') and rt.trust_network:
            trust_net = rt.trust_network
            try:
                result["score"] = round(trust_net.get_score(agent_id), 3)
                record = trust_net.get_record(agent_id)
                if record:
                    result["observations"] = int(record.observations)
                    result["uncertainty"] = round(record.uncertainty, 3)
                # Recent trend
                events = trust_net.get_events_for_agent(agent_id, n=5)
                if len(events) >= 2:
                    old = events[0].new_score
                    new = events[-1].new_score
                    if new > old + 0.02:
                        result["trend"] = "rising"
                    elif new < old - 0.02:
                        result["trend"] = "falling"
                    else:
                        result["trend"] = "stable"
            except Exception:
                logger.debug("AD-588: trust state query failed for %s", agent_id, exc_info=True)
        result["model"] = "bayesian_beta"
        result["range"] = "0.05\u20130.95"
        return result

    async def get_cognitive_state(self, agent_id: str) -> dict[str, Any]:
        """Zone, cooldown, recent posts count, self-similarity."""
        result: dict[str, Any] = {}
        agent = self._resolve_agent(agent_id)
        if agent:
            wm = getattr(agent, '_working_memory', None)
            if wm and hasattr(wm, 'get_cognitive_zone'):
                zone = wm.get_cognitive_zone()
                if zone:
                    result["zone"] = zone
        result["regulation_model"] = "graduated_zones"
        return result

    async def get_temporal_state(self, agent_id: str) -> dict[str, Any]:
        """Uptime, birth age, last action, lifecycle state."""
        result: dict[str, Any] = {}
        rt = self._runtime
        now = time.time()
        result["system_uptime_hours"] = round(
            (now - getattr(rt, '_start_time_wall', now)) / 3600, 1
        )
        agent = self._resolve_agent(agent_id)
        if agent:
            birth = getattr(agent, '_birth_timestamp', None)
            if birth:
                result["agent_age_hours"] = round((now - birth) / 3600, 1)
            if hasattr(agent, 'meta') and agent.meta.last_active:
                last_active = agent.meta.last_active
                delta = (datetime.now(timezone.utc) - last_active).total_seconds()
                result["last_action_minutes"] = round(delta / 60, 1)
        result["lifecycle"] = getattr(rt, '_lifecycle_state', 'unknown')
        return result

    async def get_social_state(self, agent_id: str) -> dict[str, Any]:
        """Routing affinities (Hebbian), interaction breadth."""
        result: dict[str, Any] = {}
        rt = self._runtime
        if hasattr(rt, 'hebbian_router') and rt.hebbian_router:
            try:
                all_weights = rt.hebbian_router.all_weights_typed()
                agent_weights = {
                    src: w for (src, tgt, rel), w in all_weights.items()
                    if tgt == agent_id and w > 0
                }
                if agent_weights:
                    top = sorted(agent_weights.items(), key=lambda x: x[1], reverse=True)[:3]
                    result["routing_affinities"] = [
                        {"intent": src, "weight": round(w, 2)} for src, w in top
                    ]
            except Exception:
                pass
        # Trust network social signals
        if hasattr(rt, 'trust_network') and rt.trust_network:
            try:
                events = rt.trust_network.get_events_for_agent(agent_id, n=20)
                unique_intents = set(e.intent_type for e in events)
                result["interaction_breadth"] = len(unique_intents)
            except Exception:
                pass
        return result

    async def get_full_snapshot(self, agent_id: str) -> dict[str, Any]:
        """All five telemetry domains combined. Best-effort — each domain independent."""
        snapshot: dict[str, Any] = {}
        for domain, getter in [
            ("memory", self.get_memory_state),
            ("trust", self.get_trust_state),
            ("cognitive", self.get_cognitive_state),
            ("temporal", self.get_temporal_state),
            ("social", self.get_social_state),
        ]:
            try:
                snapshot[domain] = await getter(agent_id)
            except Exception:
                logger.debug("AD-588: %s domain failed for %s", domain, agent_id, exc_info=True)
                snapshot[domain] = {}
        return snapshot

    @staticmethod
    def render_telemetry_context(snapshot: dict[str, Any]) -> str:
        """Render telemetry snapshot into human-readable context block."""
        if not snapshot:
            return ""

        lines: list[str] = []
        lines.append("--- Your Telemetry (ground self-referential claims in these metrics) ---")

        # Memory
        mem = snapshot.get("memory", {})
        ep_count = mem.get("episode_count", "unknown")
        offline = "no offline processing" if not mem.get("offline_processing", False) else "offline processing active"
        lines.append(
            f"Memory: {ep_count} episodes (cosine similarity retrieval, {offline})"
        )

        # Trust
        trust = snapshot.get("trust", {})
        if "score" in trust:
            trust_parts = [f"{trust['score']}"]
            if "observations" in trust:
                trust_parts.append(f"{trust['observations']} observations")
            if "uncertainty" in trust:
                trust_parts.append(f"uncertainty \u00b1{trust['uncertainty']}")
            if "trend" in trust:
                trust_parts.append(f"trend: {trust['trend']}")
            lines.append(f"Trust: {' ('.join(trust_parts[:1])}" +
                         (f" ({', '.join(trust_parts[1:])})" if len(trust_parts) > 1 else ""))
        else:
            lines.append("Trust: no record yet")

        # Cognitive zone
        cog = snapshot.get("cognitive", {})
        zone = cog.get("zone", "unknown")
        lines.append(f"Cognitive zone: {zone.upper() if isinstance(zone, str) else zone}")

        # Temporal
        temp = snapshot.get("temporal", {})
        time_parts = []
        if "system_uptime_hours" in temp:
            time_parts.append(f"Uptime: {temp['system_uptime_hours']}h")
        if "agent_age_hours" in temp:
            time_parts.append(f"Age: {temp['agent_age_hours']}h")
        if "last_action_minutes" in temp:
            time_parts.append(f"Last action: {temp['last_action_minutes']}m ago")
        if time_parts:
            lines.append(" | ".join(time_parts))

        lines.append("")
        lines.append(
            "When discussing yourself, cite these numbers. You may express warmth and"
        )
        lines.append(
            "personality \u2014 do not generate claims about architecture not reflected here."
        )
        lines.append("---")

        return "\n".join(lines)
