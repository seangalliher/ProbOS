"""FeedbackEngine — applies human feedback signals to trust, Hebbian routing, and episodic memory."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — feedback records trust outcomes
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.event_log import EventLog
    from probos.types import TaskDAG, TaskNode

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class FeedbackResult:
    """Result of applying user feedback."""

    feedback_type: str  # "positive", "negative", "rejected_plan"
    agents_updated: list[str] = dataclasses.field(default_factory=list)
    episode_stored: bool = False
    original_text: str = ""


class FeedbackEngine:
    """Applies human feedback signals to the learning substrate.

    Human feedback is the highest-quality training signal available.
    The system learns faster from human feedback than from agent-to-agent
    interactions:
    - Hebbian reward is 2x normal (0.10 vs 0.05)
    - Trust observation is 1:1 with standard (one record_outcome per agent)
    - Feedback-tagged episodes influence future planning via recall_similar()
    """

    def __init__(
        self,
        trust_network: TrustNetwork,
        hebbian_router: HebbianRouter,
        episodic_memory: EpisodicMemory | None = None,
        event_log: EventLog | None = None,
        feedback_hebbian_reward: float = 0.10,
        feedback_trust_weight: float = 1.5,
    ) -> None:
        self._trust = trust_network
        self._hebbian = hebbian_router
        self._episodic = episodic_memory
        self._event_log = event_log
        self._feedback_hebbian_reward = feedback_hebbian_reward
        self._feedback_trust_weight = feedback_trust_weight

    async def apply_execution_feedback(
        self,
        dag: TaskDAG,
        positive: bool,
        original_text: str,
    ) -> FeedbackResult:
        """Apply user feedback on an executed DAG.

        1. Hebbian updates — strengthen/weaken intent→agent connections
        2. Trust updates — record_outcome for each participating agent
        3. Episodic memory — store feedback-tagged episode
        4. Event log — record feedback event
        """
        feedback_type = "positive" if positive else "negative"
        agent_ids = self._extract_agent_ids(dag)
        intent_agent_pairs = self._extract_intent_agent_pairs(dag)

        # 1. Hebbian updates
        saved_reward = self._hebbian.reward
        self._hebbian.reward = self._feedback_hebbian_reward
        try:
            for intent, agent_id in intent_agent_pairs:
                self._hebbian.record_interaction(
                    source=intent,
                    target=agent_id,
                    success=positive,
                    rel_type="intent",
                )
        finally:
            self._hebbian.reward = saved_reward

        # Event: Hebbian update (AD-222)
        if self._event_log and intent_agent_pairs:
            try:
                await self._event_log.log(
                    category="cognitive",
                    event="feedback_hebbian_update",
                    detail=json.dumps({
                        "pairs": intent_agent_pairs,
                        "positive": positive,
                    }),
                )
            except Exception:
                pass

        # 2. Trust updates — one observation per agent
        for agent_id in agent_ids:
            self._trust.record_outcome(agent_id, success=positive)

        # Event: Trust update (AD-222)
        if self._event_log and agent_ids:
            try:
                await self._event_log.log(
                    category="cognitive",
                    event="feedback_trust_update",
                    detail=json.dumps({
                        "agents": agent_ids,
                        "positive": positive,
                    }),
                )
            except Exception:
                pass

        # 3. Episodic memory — feedback-tagged episode
        episode_stored = False
        if self._episodic:
            episode_stored = await self._store_feedback_episode(
                dag, feedback_type, original_text, agent_ids,
            )

        # Event: feedback applied (AD-222)
        if self._event_log:
            event_name = "feedback_positive" if positive else "feedback_negative"
            try:
                await self._event_log.log(
                    category="cognitive",
                    event=event_name,
                    detail=json.dumps({
                        "agents": agent_ids,
                        "intent_count": len(dag.nodes),
                        "text": original_text[:200],
                    }),
                )
            except Exception:
                pass

        result = FeedbackResult(
            feedback_type=feedback_type,
            agents_updated=agent_ids,
            episode_stored=episode_stored,
            original_text=original_text,
        )

        return result

    async def apply_correction_feedback(
        self,
        original_text: str,
        correction: Any,
        patch_result: Any,
        retry_success: bool,
    ) -> FeedbackResult:
        """Record a correction event in the learning substrate (AD-234).

        Corrections are the richest feedback signal: they encode both
        "what went wrong" and "how to fix it".
        """
        agent_type = getattr(correction, "target_agent_type", "unknown")
        correction_type = getattr(correction, "correction_type", "parameter_fix")
        corrected_values = getattr(correction, "corrected_values", {})
        changes_description = getattr(patch_result, "changes_description", "")
        agents_updated: list[str] = []

        # 1. Hebbian — strengthen/weaken intent→agent route
        target_intent = getattr(correction, "target_intent", "")
        if target_intent and agent_type:
            saved_reward = self._hebbian.reward
            self._hebbian.reward = self._feedback_hebbian_reward
            try:
                self._hebbian.record_interaction(
                    source=target_intent,
                    target=agent_type,
                    success=retry_success,
                    rel_type="intent",
                )
            finally:
                self._hebbian.reward = saved_reward
            agents_updated.append(agent_type)

        # 2. Trust — small positive if retry succeeded
        if retry_success and agent_type:
            self._trust.record_outcome(agent_type, success=True)

        # 3. Episodic memory — correction-tagged episode
        episode_stored = False
        if self._episodic:
            from probos.types import Episode

            feedback_label = (
                "correction_applied" if retry_success else "correction_failed"
            )
            outcomes: list[dict[str, Any]] = [
                {
                    "intent": target_intent or agent_type,
                    "human_feedback": feedback_label,
                    "correction_type": correction_type,
                    "corrected_values": corrected_values,
                    "changes_description": changes_description,
                    "retry_success": retry_success,
                },
            ]
            dag_summary: dict[str, Any] = {
                "correction_applied": True,
                "agent_type": agent_type,
                "correction_type": correction_type,
                "corrected_values": corrected_values,
            }
            episode = Episode(
                user_input=original_text,
                timestamp=time.time(),
                dag_summary=dag_summary,
                outcomes=outcomes,
                agent_ids=agents_updated,
                reflection=f"Correction {feedback_label}: {changes_description}",
            )
            try:
                await self._episodic.store(episode)
                episode_stored = True
            except Exception as e:
                logger.warning("Failed to store correction episode: %s", e)

        # 4. Event log
        if self._event_log:
            event_name = (
                "feedback_correction_applied"
                if retry_success
                else "feedback_correction_failed"
            )
            try:
                await self._event_log.log(
                    category="cognitive",
                    event=event_name,
                    detail=json.dumps({
                        "agent_type": agent_type,
                        "correction_type": correction_type,
                        "corrected_values": corrected_values,
                        "changes_description": changes_description,
                        "retry_success": retry_success,
                        "text": original_text[:200],
                    }),
                )
            except Exception:
                pass

        return FeedbackResult(
            feedback_type="correction_applied" if retry_success else "correction_failed",
            agents_updated=agents_updated,
            episode_stored=episode_stored,
            original_text=original_text,
        )

    async def apply_rejection_feedback(
        self,
        proposal_text: str,
        dag: TaskDAG,
    ) -> FeedbackResult:
        """Record rejection feedback — no agents executed.

        1. Episodic memory — rejection-tagged episode
        2. Event log — record plan_rejected event
        No trust or Hebbian updates (no agents executed).
        """
        episode_stored = False
        if self._episodic:
            episode_stored = await self._store_feedback_episode(
                dag, "rejected_plan", proposal_text, agent_ids=[],
            )

        # Event: plan rejected (AD-222)
        if self._event_log:
            try:
                await self._event_log.log(
                    category="cognitive",
                    event="feedback_plan_rejected",
                    detail=json.dumps({
                        "intent_count": len(dag.nodes),
                        "text": proposal_text[:200],
                    }),
                )
            except Exception:
                pass

        result = FeedbackResult(
            feedback_type="rejected_plan",
            agents_updated=[],
            episode_stored=episode_stored,
            original_text=proposal_text,
        )

        return result

    # ------------------------------------------------------------------
    # Agent ID extraction (AD-221)
    # ------------------------------------------------------------------

    def _extract_agent_ids(self, dag: TaskDAG) -> list[str]:
        """Extract unique agent IDs from an executed DAG's node results."""
        agent_ids: list[str] = []
        for node in dag.nodes:
            agent_id = self._get_agent_id_from_node(node)
            if agent_id and agent_id not in agent_ids:
                agent_ids.append(agent_id)
        return agent_ids

    def _get_agent_id_from_node(self, node: TaskNode) -> str | None:
        """Extract agent_id from a single node's result."""
        if node.result is None:
            return None
        if isinstance(node.result, dict):
            return node.result.get("agent_id")
        if hasattr(node.result, "agent_id"):
            return node.result.agent_id
        return None

    def _extract_intent_agent_pairs(self, dag: TaskDAG) -> list[tuple[str, str]]:
        """Extract (intent_name, agent_id) pairs for Hebbian updates."""
        pairs: list[tuple[str, str]] = []
        for node in dag.nodes:
            intent = node.intent
            agent_id = self._get_agent_id_from_node(node)
            if intent and agent_id:
                pairs.append((intent, agent_id))
        return pairs

    # ------------------------------------------------------------------
    # Episode storage (AD-218)
    # ------------------------------------------------------------------

    async def _store_feedback_episode(
        self,
        dag: TaskDAG,
        feedback_type: str,
        original_text: str,
        agent_ids: list[str],
    ) -> bool:
        """Store a feedback-tagged episode in episodic memory."""
        if not self._episodic:
            return False

        from probos.types import Episode

        # Build outcomes list tagged with feedback type
        outcome_label = {
            "positive": "human_positive",
            "negative": "human_negative",
            "rejected_plan": "plan_rejected",
        }.get(feedback_type, feedback_type)

        outcomes: list[dict[str, Any]] = [
            {"intent": node.intent, "human_feedback": feedback_type}
            for node in dag.nodes
        ]
        if not outcomes:
            outcomes = [{"human_feedback": feedback_type}]

        # Build dag summary
        dag_summary: dict[str, Any] = {
            "intents": [node.intent for node in dag.nodes],
            "node_count": len(dag.nodes),
            "human_feedback": feedback_type,
        }

        episode = Episode(
            user_input=original_text,
            timestamp=time.time(),
            dag_summary=dag_summary,
            outcomes=outcomes,
            agent_ids=agent_ids,
            reflection=f"Human feedback: {feedback_type}",
        )

        try:
            await self._episodic.store(episode)
            return True
        except Exception as e:
            logger.warning("Failed to store feedback episode: %s", e)
            return False
