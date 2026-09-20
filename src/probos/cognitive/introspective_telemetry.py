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
import math
import time
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from probos.cognitive.episodic import resolve_sovereign_id, resolve_sovereign_id_from_slot
from probos.cognitive.self_telemetry_domains import (
    collect_authority_state,
    collect_wellness_state,
    render_optional_domains,
)
from probos.config import format_trust

logger = logging.getLogger(__name__)

MEMORY_POPULATION = "stored_agent_membership"
MEMORY_SOURCE = "episodic_memory.count_for_agent"
UPTIME_POPULATION = "system_runtime"
UPTIME_SOURCE = "runtime.get_uptime_seconds"


class _EpisodicCount(Protocol):
    @property
    def is_available(self) -> bool: ...

    async def count_for_agent(self, agent_id: str) -> int: ...


class _RuntimeUptime(Protocol):
    def get_uptime_seconds(self) -> float | None: ...


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
        """Stored membership total, including shared and self-contradicted episodes."""
        result: dict[str, Any] = {}
        rt = self._runtime
        measurement: dict[str, Any] = {
            "subject_id": None,
            "population": MEMORY_POPULATION,
            "unit": "episodes",
            "source": MEMORY_SOURCE,
            "sample_started_at": datetime.now(timezone.utc).isoformat(),
            "sample_completed_at": None,
            "status": "unavailable",
        }
        try:
            if type(agent_id) is str and agent_id:
                agent = self._resolve_agent(agent_id)
                subject = (
                    resolve_sovereign_id(agent) if agent is not None
                    else resolve_sovereign_id_from_slot(
                        agent_id, getattr(rt, "identity_registry", None),
                    )
                )
                if type(subject) is not str or not subject:
                    raise ValueError("Invalid memory subject")
                measurement["subject_id"] = subject
                memory = cast(_EpisodicCount | None, getattr(rt, "episodic_memory", None))
                if memory is not None:
                    result["episode_count"] = "unknown"
                    if getattr(memory, "is_available", None) is True:
                        count = await memory.count_for_agent(subject)
                        if type(count) is not int or count < 0:
                            raise ValueError("Invalid memory count")
                        if memory.is_available is True:
                            result["episode_count"] = count
                            measurement["status"] = "available"
            else:
                result["episode_count"] = "unknown"
        except Exception:
            result["episode_count"] = "unknown"
            measurement["status"] = "failed"
            logger.warning(
                "Memory measurement failed; episode count is unknown, "
                "returning remaining telemetry"
            )
        measurement["sample_completed_at"] = datetime.now(timezone.utc).isoformat()
        result["measurement"] = measurement
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
                result["score"] = format_trust(trust_net.get_score(agent_id))
                record = trust_net.get_record(agent_id)
                if record:
                    result["observations"] = int(record.observations)
                    result["uncertainty"] = format_trust(record.uncertainty)
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
        # BF-161: Default to green (circuit breaker default) instead of leaving
        # empty, which caused downstream renders to show "UNKNOWN".
        if "zone" not in result:
            result["zone"] = "green"
        result["regulation_model"] = "graduated_zones"
        return result

    async def get_temporal_state(self, agent_id: str) -> dict[str, Any]:
        """Uptime, birth age, last action, lifecycle state."""
        result: dict[str, Any] = {}
        rt = self._runtime
        measurement: dict[str, Any] = {
            "subject_id": "system",
            "population": UPTIME_POPULATION,
            "unit": "seconds",
            "source": UPTIME_SOURCE,
            "sample_started_at": datetime.now(timezone.utc).isoformat(),
            "sample_completed_at": None,
            "status": "unavailable",
        }
        try:
            clock = cast(_RuntimeUptime, rt)
            if callable(getattr(clock, "get_uptime_seconds", None)):
                seconds = clock.get_uptime_seconds()
                if seconds is not None:
                    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                        raise ValueError("Invalid runtime uptime")
                    result["system_uptime_seconds"] = round(seconds, 1)
                    result["system_uptime_hours"] = round(result["system_uptime_seconds"] / 3600, 1)
                    measurement["status"] = "available"
        except Exception:
            measurement["status"] = "failed"
            logger.warning(
                "Runtime uptime measurement failed; duration is unknown, "
                "returning remaining temporal signals"
            )
        measurement["sample_completed_at"] = datetime.now(timezone.utc).isoformat()
        result["uptime_measurement"] = measurement
        try:
            now = time.time()
            agent = self._resolve_agent(agent_id)
            if agent:
                birth = getattr(agent, '_birth_timestamp', None)
                if birth:
                    result["agent_age_hours"] = round((now - birth) / 3600, 1)
                if hasattr(agent, 'meta') and agent.meta.last_active:
                    last_active = agent.meta.last_active
                    delta = (datetime.now(timezone.utc) - last_active).total_seconds()
                    result["last_action_minutes"] = round(delta / 60, 1)
        except Exception:
            logger.warning(
                "Agent temporal signals failed; age or last action is unknown, "
                "preserving the runtime uptime measurement"
            )
        result["lifecycle"] = getattr(rt, '_lifecycle_state', 'unknown')
        return result

    async def get_social_state(self, agent_id: str) -> dict[str, Any]:
        """Hebbian graph projections, incident connections, interaction breadth."""
        result: dict[str, Any] = {}
        rt = self._runtime
        try:
            router = getattr(rt, 'hebbian_router', None)
            if router is None:
                logger.warning(
                    "AD-1259: Hebbian router unavailable; returning available "
                    "interaction signals without graph facts"
                )
            else:
                all_weights = router.all_weights_typed()
                incoming: list[tuple[str, float]] = []
                outgoing: list[tuple[str, float]] = []
                routing_weights: dict[str, float] = {}
                total_connections = 0
                for (source, target, _relation), weight in all_weights.items():
                    if source == agent_id or target == agent_id:
                        total_connections += 1
                    if target == agent_id:
                        incoming.append((source, weight))
                        if weight > 0:
                            routing_weights[source] = weight
                    if source == agent_id:
                        outgoing.append((target, weight))

                graph: dict[str, Any] = {"total_connections": total_connections}
                for key, affinities in (
                    ("routing_affinities", list(routing_weights.items())),
                    ("incoming_affinities", incoming),
                    ("outbound_affinities", outgoing),
                ):
                    if affinities:
                        top = sorted(affinities, key=lambda entry: entry[1], reverse=True)[:3]
                        graph[key] = [
                            {"intent": endpoint, "weight": format_trust(weight)}
                            for endpoint, weight in top
                        ]
                result.update(graph)
        except Exception:
            logger.warning(
                "AD-1259: Hebbian graph collection failed; returning available "
                "interaction signals without graph facts"
            )
        # Trust network social signals
        if hasattr(rt, 'trust_network') and rt.trust_network:
            try:
                events = rt.trust_network.get_events_for_agent(agent_id, n=20)
                unique_intents = set(e.intent_type for e in events)
                result["interaction_breadth"] = len(unique_intents)
            except Exception:
                pass
        return result

    async def get_wellness_state(self, agent_id: str) -> dict[str, Any]:
        """Explicit first-person read of the Counselor's stored assessment."""
        return collect_wellness_state(
            agent_id, registry=getattr(self._runtime, "registry", None),
        )

    async def get_authority_state(self, agent_id: str) -> dict[str, Any]:
        """Explicit first-person read of effective tool permissions."""
        return collect_authority_state(
            agent_id,
            agent_registry=getattr(self._runtime, "registry", None),
            ontology=getattr(self._runtime, "ontology", None),
            trust_network=getattr(self._runtime, "trust_network", None),
            tool_registry=getattr(self._runtime, "tool_registry", None),
        )

    async def get_full_snapshot(
        self, agent_id: str, *, extra_domains: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Five operational domains plus explicit extras, independently collected."""
        if type(extra_domains) is not tuple or any(
            type(domain) is not str for domain in extra_domains
        ):
            raise ValueError("extra_domains must be a tuple of strings")
        snapshot: dict[str, Any] = {}
        getters = [
            ("memory", self.get_memory_state),
            ("trust", self.get_trust_state),
            ("cognitive", self.get_cognitive_state),
            ("temporal", self.get_temporal_state),
            ("social", self.get_social_state),
        ]
        for domain in ("wellness", "authority"):
            if domain in extra_domains:
                getters.append((domain, getattr(self, f"get_{domain}_state")))
        for domain, getter in getters:
            try:
                snapshot[domain] = await getter(agent_id)
            except Exception:
                if domain in ("wellness", "authority"):
                    logger.warning(
                        "Optional %s telemetry failed; this domain is unknown, "
                        "preserving the remaining snapshot", domain,
                    )
                else:
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
        if "memory" in snapshot:
            mem = snapshot["memory"]
            ep_count = mem.get("episode_count", "unknown")
            offline = "no offline processing" if not mem.get("offline_processing", False) else "offline processing active"
            lines.append(
                f"Memory: {ep_count} episodes (cosine similarity retrieval, {offline})"
            )

        # Trust
        if "trust" in snapshot:
            trust = snapshot["trust"]
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
        if "cognitive" in snapshot:
            cog = snapshot["cognitive"]
            zone = cog.get("zone", "unknown")
            lines.append(f"Cognitive zone: {zone.upper() if isinstance(zone, str) else zone}")

        # Temporal
        if "temporal" in snapshot:
            temp = snapshot["temporal"]
            time_parts = []
            if "system_uptime_hours" in temp:
                time_parts.append(f"Uptime: {temp['system_uptime_hours']}h")
            elif "uptime_measurement" in temp:
                time_parts.append(f"Uptime: unknown ({temp['uptime_measurement']['status']})")
            if "agent_age_hours" in temp:
                time_parts.append(f"Age: {temp['agent_age_hours']}h")
            if "last_action_minutes" in temp:
                time_parts.append(f"Last action: {temp['last_action_minutes']}m ago")
            if time_parts:
                lines.append(" | ".join(time_parts))

        for domain, key, label in (
            ("memory", "measurement", "Memory measurement"),
            ("temporal", "uptime_measurement", "System uptime measurement"),
        ):
            measurement = snapshot.get(domain, {}).get(key)
            if measurement:
                lines.append(
                    f"{label}: {measurement['status']}; "
                    f"subject={measurement['subject_id'] or 'unknown'}; "
                    f"population={measurement['population']}; "
                    f"unit={measurement['unit']}; source={measurement['source']}"
                )

        social = snapshot.get("social") or {}
        social_parts: list[str] = []
        affinities = social.get("routing_affinities", [])
        if affinities:
            affinity_text = ", ".join(
                f"{affinity.get('intent', '?')} ({affinity.get('weight', '?')})"
                for affinity in affinities
            )
            social_parts.append(f"routing affinities: {affinity_text}")
        if "interaction_breadth" in social:
            social_parts.append(f"interaction breadth: {social['interaction_breadth']}")
        if social_parts:
            lines.append(f"Collaboration: {' | '.join(social_parts)}")

        lines.extend(render_optional_domains(snapshot))

        lines.append("")
        lines.append(
            "When discussing yourself, cite these numbers. You may express warmth and"
        )
        lines.append(
            "personality \u2014 do not generate claims about architecture not reflected here."
        )
        lines.append("---")

        return "\n".join(lines)
