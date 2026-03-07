"""Quorum engine — configurable consensus with confidence-weighted voting."""

from __future__ import annotations

import logging
from typing import Any

from probos.types import (
    AgentID,
    ConsensusOutcome,
    ConsensusResult,
    IntentResult,
    QuorumPolicy,
    Vote,
)

logger = logging.getLogger(__name__)


class QuorumEngine:
    """Evaluates consensus from multiple agent results.

    Supports configurable thresholds (2-of-3, 3-of-5, etc.) and
    confidence-weighted voting where each agent's vote weight is
    scaled by their confidence score.
    """

    def __init__(self, policy: QuorumPolicy | None = None) -> None:
        self.policy = policy or QuorumPolicy()

    def evaluate(
        self,
        results: list[IntentResult],
        policy: QuorumPolicy | None = None,
    ) -> ConsensusResult:
        """Evaluate consensus from a set of intent results.

        Each IntentResult is treated as a vote:
        - success=True → approval vote
        - success=False → rejection vote
        - Vote weight = agent confidence (if confidence weighting enabled)

        Returns a ConsensusResult with the outcome.
        """
        policy = policy or self.policy

        if len(results) < policy.min_votes:
            return ConsensusResult(
                proposal_id=results[0].intent_id if results else "",
                outcome=ConsensusOutcome.INSUFFICIENT,
                votes=[],
                policy=policy,
            )

        votes: list[Vote] = []
        weighted_approval = 0.0
        weighted_rejection = 0.0
        total_weight = 0.0

        for r in results:
            weight = r.confidence if policy.use_confidence_weights else 1.0
            vote = Vote(
                agent_id=r.agent_id,
                approved=r.success,
                confidence=r.confidence,
                reason=r.error or "",
            )
            votes.append(vote)
            total_weight += weight

            if r.success:
                weighted_approval += weight
            else:
                weighted_rejection += weight

        # Determine outcome
        if total_weight == 0:
            outcome = ConsensusOutcome.INSUFFICIENT
        elif (weighted_approval / total_weight) >= policy.approval_threshold:
            outcome = ConsensusOutcome.APPROVED
        else:
            outcome = ConsensusOutcome.REJECTED

        proposal_id = results[0].intent_id if results else ""

        result = ConsensusResult(
            proposal_id=proposal_id,
            outcome=outcome,
            votes=votes,
            weighted_approval=weighted_approval,
            weighted_rejection=weighted_rejection,
            total_weight=total_weight,
            policy=policy,
        )

        logger.info(
            "Quorum evaluated: proposal=%s outcome=%s approval=%.3f/%.3f "
            "votes=%d threshold=%.1f%%",
            proposal_id[:8],
            outcome.value,
            weighted_approval,
            total_weight,
            len(votes),
            policy.approval_threshold * 100,
        )

        return result

    def evaluate_values(
        self,
        results: list[IntentResult],
        policy: QuorumPolicy | None = None,
    ) -> tuple[ConsensusResult, Any]:
        """Evaluate consensus and return the majority result value.

        First evaluates quorum approval. If approved, determines the
        consensus value by confidence-weighted majority among agreeing agents.

        Returns (consensus_result, majority_value).
        majority_value is None if consensus was not reached.
        """
        consensus = self.evaluate(results, policy)
        if consensus.outcome != ConsensusOutcome.APPROVED:
            return consensus, None

        # Find the majority value among successful results
        successful = [r for r in results if r.success]
        if not successful:
            return consensus, None

        # Group by result value, weight by confidence
        value_weights: dict[str, float] = {}
        value_map: dict[str, Any] = {}
        for r in successful:
            key = str(r.result)
            weight = r.confidence if (policy or self.policy).use_confidence_weights else 1.0
            value_weights[key] = value_weights.get(key, 0.0) + weight
            value_map[key] = r.result

        # Pick the value with highest total weight
        best_key = max(value_weights, key=value_weights.get)  # type: ignore[arg-type]
        return consensus, value_map[best_key]
