"""AD-515: Dream adapter extracted from ProbOSRuntime.

Handles dream callbacks, periodic flush, episode building, and emergent detection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from probos.config import format_trust
from probos.events import EventType
from probos.types import Episode, MemorySource

if TYPE_CHECKING:
    from probos.bridge_alerts import BridgeAlertService
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.dreaming import DreamScheduler
    from probos.cognitive.emergent_detector import EmergentDetector
    from probos.cognitive.episodic import EpisodicMemory
    from probos.cognitive.self_mod import SelfModificationPipeline
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.knowledge.store import KnowledgeStore
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.event_log import EventLog
    from probos.substrate.pool import ResourcePool
    from probos.substrate.registry import AgentRegistry
    from probos.ward_room import WardRoomService

logger = logging.getLogger(__name__)


class DreamAdapter:
    """Bridges dream scheduler callbacks to runtime services."""

    def __init__(
        self,
        *,
        dream_scheduler: DreamScheduler | None,
        emergent_detector: EmergentDetector | None,
        episodic_memory: EpisodicMemory | None,
        knowledge_store: KnowledgeStore | None,
        hebbian_router: HebbianRouter,
        trust_network: TrustNetwork,
        event_emitter: Callable,
        self_mod_pipeline: SelfModificationPipeline | None,
        bridge_alerts: BridgeAlertService | None,
        ward_room: WardRoomService | None,
        registry: AgentRegistry,
        event_log: EventLog | None,
        config: SystemConfig,
        pools: dict[str, ResourcePool],
        behavioral_monitor: BehavioralMonitor | None = None,
        deliver_bridge_alert_fn: Callable | None = None,
    ) -> None:
        self._dream_scheduler = dream_scheduler
        self._emergent_detector = emergent_detector
        self._episodic_memory = episodic_memory
        self._knowledge_store = knowledge_store
        self._hebbian_router = hebbian_router
        self._trust_network = trust_network
        self._event_emitter = event_emitter
        self._self_mod_pipeline = self_mod_pipeline
        self._bridge_alerts = bridge_alerts
        self._ward_room = ward_room
        self._registry = registry
        self._event_log = event_log
        self._config = config
        self._pools = pools
        self._behavioral_monitor = behavioral_monitor
        self._deliver_bridge_alert_fn = deliver_bridge_alert_fn

        # Runtime state references (set by runtime after creation)
        self._cold_start: bool = False
        self._last_shapley_values: dict[str, float] | None = None

    async def recall_similar(self, query: str, k: int = 5) -> list[Episode]:
        """Recall similar past episodes from episodic memory."""
        if not self._episodic_memory:
            return []
        return await self._episodic_memory.recall(query, k=k)

    def on_pre_dream(self) -> None:
        """Pre-dream callback: emit system_mode event for HXI (AD-254)."""
        self._event_emitter(EventType.SYSTEM_MODE, {"mode": "dreaming", "previous": "idle"})

    def refresh_emergent_detector_roster(self) -> None:
        """Update EmergentDetector with the current live agent roster."""
        if not self._emergent_detector:
            return
        live_ids: set[str] = set()
        for pool in self._pools.values():
            for agent_id in pool.healthy_agents:
                aid = agent_id if isinstance(agent_id, str) else agent_id.id
                live_ids.add(aid)
        self._emergent_detector.set_live_agents(live_ids)

    def on_post_dream(self, dream_report: Any) -> None:
        """Post-dream callback: run emergent detection and log patterns (AD-237)."""
        # BF-034: Clear cold-start flag after first dream cycle
        if self._cold_start:
            self._cold_start = False
            logger.info("BF-034: Cold start period ended — normal detection resumed")

        # Emit system_mode event for HXI (AD-254) — dream cycle ended
        self._event_emitter(EventType.SYSTEM_MODE, {"mode": "idle", "previous": "dreaming"})

        # AD-557: Emit emergence metrics events
        if dream_report and getattr(dream_report, "emergence_capacity", None) is not None:
            self._event_emitter(EventType.EMERGENCE_METRICS_UPDATED, {
                "emergence_capacity": dream_report.emergence_capacity,
                "coordination_balance": dream_report.coordination_balance,
                "groupthink_risk": dream_report.groupthink_risk,
                "fragmentation_risk": dream_report.fragmentation_risk,
                "tom_effectiveness": dream_report.tom_effectiveness,
            })
            if dream_report.groupthink_risk:
                self._event_emitter(EventType.GROUPTHINK_WARNING, {
                    "redundancy_ratio": getattr(dream_report, "redundancy_ratio", 0.0),
                })
            if dream_report.fragmentation_risk:
                self._event_emitter(EventType.FRAGMENTATION_WARNING, {
                    "synergy_ratio": getattr(dream_report, "synergy_ratio", 0.0),
                    "pairs_analyzed": getattr(dream_report, "pairs_analyzed", 0),
                })

        if not self._emergent_detector:
            return
        try:
            patterns = self._emergent_detector.analyze(dream_report=dream_report, duty_completions=[])
            for pattern in patterns:
                # Fire-and-forget event logging (sync context, schedule coroutine)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._event_log_emergent(pattern))
                except RuntimeError:
                    pass  # No running loop — skip logging

            # AD-410: Bridge Alerts from emergent patterns
            if self._bridge_alerts and patterns and self._deliver_bridge_alert_fn:
                emergent_alerts = self._bridge_alerts.check_emergent_patterns(patterns)
                for ea in emergent_alerts:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._deliver_bridge_alert_fn(ea))
                    except RuntimeError:
                        pass

        except Exception as e:
            logger.debug("Post-dream emergent analysis failed: %s", e)

        # AD-410: Bridge Alerts from behavioral monitor
        if self._bridge_alerts and self._behavioral_monitor and self._deliver_bridge_alert_fn:
            behavioral_alerts = self._bridge_alerts.check_behavioral(self._behavioral_monitor)
            for ba in behavioral_alerts:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._deliver_bridge_alert_fn(ba))
                except RuntimeError:
                    pass

        # AD-410: Bridge Alerts from vitals snapshot
        if self._bridge_alerts and self._deliver_bridge_alert_fn:
            vitals_agent = None
            for agent in self._registry.get_by_pool("medical_vitals"):
                if hasattr(agent, "_window") and agent._window:
                    vitals_agent = agent
                    break
            if vitals_agent and vitals_agent._window:
                latest = vitals_agent._window[-1]
                vitals_data = {
                    "pool_health": latest.get("pool_health", {}),
                    "system_health": latest.get("system_health"),
                    "trust_outlier_count": len(latest.get("trust_outliers", [])),
                }
                vitals_alerts = self._bridge_alerts.check_vitals(vitals_data)
                for va in vitals_alerts:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._deliver_bridge_alert_fn(va))
                    except RuntimeError:
                        pass

    async def _event_log_emergent(self, pattern: Any) -> None:
        """Log emergent pattern to event log (async)."""
        if self._event_log:
            await self._event_log.log(
                category="emergent",
                event=pattern.pattern_type,
                detail=pattern.description,
            )

    def on_gap_predictions(self, predictions: list[Any]) -> None:
        """Broadcast gap predictions to HXI (AD-385)."""
        for p in predictions:
            self._event_emitter(EventType.CAPABILITY_GAP_PREDICTED, p.to_dict())
        logger.info("Dream cycle predicted %d capability gaps", len(predictions))

    def on_contradictions(self, contradictions: list[Any]) -> None:
        """Log detected memory contradictions for review (AD-403)."""
        for c in contradictions:
            logger.info(
                "Memory contradiction: %s+%s — older %s (%s) vs newer %s (%s), "
                "similarity=%.2f",
                c.intent, c.agent_id,
                c.older_episode_id[:8], c.older_outcome,
                c.newer_episode_id[:8], c.newer_outcome,
                c.similarity,
            )

    def on_post_micro_dream(self, micro_report: dict[str, Any]) -> None:
        """Post-micro-dream callback: update emergent detector (AD-288)."""
        if not self._emergent_detector:
            return
        # AD-417: Skip analysis during proactive-busy periods to reduce noise.
        if self._dream_scheduler and self._dream_scheduler.is_proactively_busy:
            return
        try:
            self._emergent_detector.analyze(dream_report=micro_report, duty_completions=[])
        except Exception as e:
            logger.debug("Post-micro-dream analysis failed: %s", e)

    async def periodic_flush(self) -> None:
        """Save trust scores and routing weights to KnowledgeStore."""
        if self._knowledge_store is None:
            return
        try:
            await self._knowledge_store.store_trust_snapshot(
                self._trust_network.raw_scores()
            )
            weights = [
                {"source": s, "target": t, "rel_type": rt, "weight": w}
                for (s, t, rt), w in self._hebbian_router.all_weights_typed().items()
            ]
            await self._knowledge_store.store_routing_weights(weights)
            logger.debug("Periodic flush: trust + routing saved")
        except Exception:
            logger.debug("Periodic flush failed", exc_info=True)

    async def periodic_flush_loop(self) -> None:
        """Background loop that flushes trust + routing every 60s."""
        try:
            while True:
                await asyncio.sleep(60)
                await self.periodic_flush()
        except asyncio.CancelledError:
            return

    def build_episode(
        self,
        text: str,
        execution_result: dict[str, Any],
        t_start: float,
        t_end: float,
    ) -> Episode:
        """Build an Episode dataclass from execution results."""
        dag = execution_result.get("dag")
        results = execution_result.get("results", {})

        dag_summary: dict[str, Any] = {}
        outcomes: list[dict[str, Any]] = []
        agent_ids: list[str] = []

        if dag and hasattr(dag, "nodes"):
            intent_types = [n.intent for n in dag.nodes]
            dag_summary = {
                "node_count": len(dag.nodes),
                "intent_types": intent_types,
                "has_dependencies": any(n.depends_on for n in dag.nodes),
            }
            for node in dag.nodes:
                node_result = results.get(node.id, {})
                outcome: dict[str, Any] = {
                    "intent": node.intent,
                    "success": node.status == "completed",
                    "status": node.status,
                }
                # Extract agent IDs from the result
                if isinstance(node_result, dict):
                    node_results = node_result.get("results", [])
                    if isinstance(node_results, list):
                        for r in node_results:
                            aid = r.get("agent_id") if isinstance(r, dict) else getattr(r, "agent_id", None)
                            if aid:
                                agent_ids.append(aid)
                outcomes.append(outcome)

        reflection = execution_result.get("reflection")

        # Capture Shapley attribution from the most recent consensus (AD-295b)
        shapley_values = dict(self._last_shapley_values) if self._last_shapley_values else {}

        # Capture trust deltas generated during this episode (AD-295b)
        trust_deltas: list[dict[str, Any]] = []
        if self._trust_network:
            recent_events = self._trust_network.get_events_since(t_start)
            trust_deltas = [
                {
                    "agent_id": e.agent_id,
                    "old": format_trust(e.old_score),
                    "new": format_trust(e.new_score),
                    "weight": format_trust(e.weight),
                }
                for e in recent_events
            ]

        return Episode(
            timestamp=time.time(),
            user_input=text,
            dag_summary=dag_summary,
            outcomes=outcomes,
            reflection=reflection if isinstance(reflection, str) else None,
            agent_ids=agent_ids,
            duration_ms=(t_end - t_start) * 1000,
            shapley_values=shapley_values,
            trust_deltas=trust_deltas,
            source=MemorySource.DIRECT,
        )
