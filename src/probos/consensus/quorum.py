"""Quorum engine — configurable consensus with confidence-weighted voting."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from probos.governance.policy_engine import TenantPolicyEngine
from probos.security.permission_card import card_from_intent
from probos.security.destructive_ops import DestructiveOpsGuard
from probos.security.permission_model import PermissionConfig, should_auto_approve
from probos.types import IntentMessage
from probos.consensus.shapley import compute_shapley_values
from probos.types import (
    AgentID,
    ConsensusOutcome,
    ConsensusResult,
    IntentResult,
    QuorumPolicy,
    Vote,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QuorumResult:
    """Permission gate result prior to standard consensus voting."""

    approved: bool
    reason: str


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

        # Compute Shapley attribution (AD-224)
        if votes and outcome != ConsensusOutcome.INSUFFICIENT:
            result.shapley_values = compute_shapley_values(
                votes,
                approval_threshold=policy.approval_threshold,
                use_confidence_weights=policy.use_confidence_weights,
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


async def vote_on_intent(
    intent: IntentMessage,
    config: PermissionConfig,
    *,
    policy_engine: TenantPolicyEngine,
    standard_quorum_voting: Callable[[], Awaitable[QuorumResult]],
) -> QuorumResult:
    """Apply AD-753 permission gates before running standard quorum voting."""
    scope = str(intent.params.get("scope") or "unspecified")
    reason = str(intent.params.get("reason") or "permission_check")
    ttl_sec_raw = intent.params.get("ttl_sec")
    ttl_sec = int(ttl_sec_raw) if isinstance(ttl_sec_raw, int) else config.read_only_expiry_window_sec
    card = card_from_intent(intent=intent.intent, reason=reason, scope=scope, ttl_sec=ttl_sec)

    destructive_guard = DestructiveOpsGuard()
    if await destructive_guard.check_and_log(intent.intent):
        await policy_engine.audit_log(card, "destructive_requires_quorum")
        return await standard_quorum_voting()

    if await should_auto_approve(intent.intent, config):
        logger.info(
            "AD-753: auto-approved read-only intent=%s under mode=%s",
            intent.intent,
            config.mode.value,
        )
        return QuorumResult(approved=True, reason="auto_approve_read_only")

    if await policy_engine.evaluate_permission(card):
        await policy_engine.audit_log(card, "policy_approved")
        logger.info("AD-753: policy engine approved intent=%s", intent.intent)
        return QuorumResult(approved=True, reason="policy_approved")

    logger.info("AD-753: policy denied intent=%s; falling back to standard quorum", intent.intent)
    return await standard_quorum_voting()
