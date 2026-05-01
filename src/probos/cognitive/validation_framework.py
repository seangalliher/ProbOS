"""AD-451: Validation Framework Hardening.

Layered policies over existing RedTeamAgent.verify() and SystemQAAgent.
Does NOT change those APIs. Composes existing primitives into stricter
outcome-verification flows.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from probos.events import EventType

if TYPE_CHECKING:
    from probos.agents.red_team import RedTeamAgent
    from probos.types import IntentMessage, IntentResult, VerificationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MetadataCheck:
    """Internal result of TwoStageVerifier's metadata-only stage.

    Module-level (not nested) per ProbOS convention — no nested dataclasses
    elsewhere in src/probos. Leading underscore marks it private to this module.
    """

    confidence: float
    discrepancy: str


@dataclass(frozen=True)
class TwoStageOutcome:
    """Result of a two-stage verification."""

    verified: bool
    metadata_only: bool
    metadata_confidence: float
    live_confidence: float
    discrepancy: str
    target_agent_id: str
    intent_id: str
    completed_at: float


class TwoStageVerifier:
    """Wraps a RedTeamAgent. Metadata first, live only when ambiguous.

    Stateless. Each verify() call is independent. Caller is responsible
    for selecting the RedTeamAgent instance.

    v1 metadata check is a discrete-bucket classifier (no-result / error /
    success-False / success-True). Richer gradient checks are deferred to
    AD-451b.
    """

    DEFAULT_METADATA_THRESHOLD = 0.85

    def __init__(
        self,
        *,
        red_team: "RedTeamAgent",
        emit_event: Any | None = None,
        metadata_threshold: float = DEFAULT_METADATA_THRESHOLD,
    ) -> None:
        self._red_team = red_team
        self._emit_event = emit_event
        self._metadata_threshold = metadata_threshold

    async def verify(
        self,
        *,
        target_agent_id: str,
        intent: "IntentMessage",
        claimed: "IntentResult",
    ) -> TwoStageOutcome:
        """Two-stage verification. Returns TwoStageOutcome regardless of path."""
        meta = self._metadata_check(intent, claimed)
        now = time.time()

        if meta.confidence >= self._metadata_threshold and not meta.discrepancy:
            outcome = TwoStageOutcome(
                verified=True,
                metadata_only=True,
                metadata_confidence=meta.confidence,
                live_confidence=0.0,
                discrepancy="",
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                completed_at=now,
            )
            self._emit(outcome)
            return outcome

        live = await self._red_team.verify(
            target_agent_id, intent, claimed,
        )
        outcome = TwoStageOutcome(
            verified=live.verified,
            metadata_only=False,
            metadata_confidence=meta.confidence,
            live_confidence=live.confidence,
            discrepancy=live.discrepancy or meta.discrepancy,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            completed_at=time.time(),
        )
        self._emit(outcome)
        return outcome

    def _metadata_check(
        self,
        intent: "IntentMessage",
        claimed: "IntentResult",
    ) -> _MetadataCheck:
        """Cheap metadata check. Discrete buckets in v1.

        v1: presence of result, error flag, success flag.
        AD-451b will add domain-specific gradient checks (file-size, hash, ...).
        """
        if not claimed:
            return _MetadataCheck(0.0, "no result")
        if getattr(claimed, "error", None):
            return _MetadataCheck(
                0.30, f"error reported: {claimed.error}",
            )
        if not getattr(claimed, "success", True):
            return _MetadataCheck(0.30, "success=False")
        return _MetadataCheck(0.95, "")

    def _emit(self, outcome: TwoStageOutcome) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.VALIDATION_OUTCOME_VERIFIED,
                {
                    "verified": outcome.verified,
                    "metadata_only": outcome.metadata_only,
                    "metadata_confidence": outcome.metadata_confidence,
                    "live_confidence": outcome.live_confidence,
                    "target_agent_id": outcome.target_agent_id,
                    "intent_id": outcome.intent_id,
                },
            )
        except Exception:
            logger.warning(
                "AD-451: VALIDATION_OUTCOME_VERIFIED emit failed "
                "(target=%s, intent=%s)",
                outcome.target_agent_id, outcome.intent_id, exc_info=True,
            )


@runtime_checkable
class SelfVerificationHook(Protocol):
    """Optional protocol — agents may implement to self-check between act() and report().

    Returns (passed: bool, reason: str). False causes the caller to skip
    `report()` and surface a discrepancy. The hook is purely advisory; the
    caller decides what to do with a False result.

    Decorated `@runtime_checkable` so tests can assert via `isinstance(impl,
    SelfVerificationHook)` (matches the convention in src/probos/protocols.py
    where every Protocol meant for isinstance use is decorated).

    v1 callers: none — AD-451 ships the protocol; AD-451b will wire it into
    CognitiveAgent.act().
    """

    async def self_verify(self, intent: Any, result: Any) -> tuple[bool, str]:
        ...


@dataclass(frozen=True)
class ReconciliationOutcome:
    """Outcome of a verification reconciliation."""

    chosen_verdict: bool
    primary_confidence: float
    secondary_confidence: float
    third_invoked: bool
    target_agent_id: str
    intent_id: str
    reason: str


class ReconciliationEscalator:
    """Resolves disagreements between two verifiers on the same outcome.

    Algorithm:
    - If primary and secondary agree, return early (no third needed).
    - If confidence delta > min_confidence_delta, accept the higher-confidence verdict.
    - Otherwise invoke a third independent RedTeamAgent (excluding the agents
      that produced primary/secondary) via TwoStageVerifier (metadata-fast-path,
      live re-execution only when ambiguous) and majority-vote.
    - If no third is available (red_team_agents pool < 3 or all already used),
      log-and-degrade: accept the higher-confidence verdict.

    No mutation of trust; reconciliation outcomes are diagnostic only.

    The third opinion is selected at random from the eligible pool to avoid
    always-picking-the-same-agent bias.
    """

    MIN_CONFIDENCE_DELTA = 0.20

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        min_confidence_delta: float = MIN_CONFIDENCE_DELTA,
        metadata_threshold: float = TwoStageVerifier.DEFAULT_METADATA_THRESHOLD,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._min_confidence_delta = min_confidence_delta
        self._metadata_threshold = metadata_threshold

    async def reconcile(
        self,
        *,
        target_agent_id: str,
        intent: "IntentMessage",
        claimed: "IntentResult",
        primary: "VerificationResult",
        secondary: "VerificationResult",
    ) -> ReconciliationOutcome:
        if primary.verified == secondary.verified:
            return ReconciliationOutcome(
                chosen_verdict=primary.verified,
                primary_confidence=primary.confidence,
                secondary_confidence=secondary.confidence,
                third_invoked=False,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                reason="agreement",
            )

        delta = abs(primary.confidence - secondary.confidence)
        if delta >= self._min_confidence_delta:
            verdict = primary.verified if primary.confidence > secondary.confidence else secondary.verified
            outcome = ReconciliationOutcome(
                chosen_verdict=verdict,
                primary_confidence=primary.confidence,
                secondary_confidence=secondary.confidence,
                third_invoked=False,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                reason="confidence_delta",
            )
            self._emit(outcome)
            return outcome

        # Confidence delta too small — invoke a third verifier (excluding
        # the agents that produced primary and secondary).
        exclude = {primary.verifier_id, secondary.verifier_id}
        third = await self._invoke_third(
            target_agent_id=target_agent_id,
            intent=intent,
            claimed=claimed,
            exclude_ids=exclude,
        )
        if third is None:
            verdict = primary.verified if primary.confidence > secondary.confidence else secondary.verified
            outcome = ReconciliationOutcome(
                chosen_verdict=verdict,
                primary_confidence=primary.confidence,
                secondary_confidence=secondary.confidence,
                third_invoked=False,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                reason="third_unavailable",
            )
            self._emit(outcome)
            return outcome

        # Use the boolean .verified from the TwoStageOutcome
        votes = sum([primary.verified, secondary.verified, third.verified])
        majority = votes >= 2
        outcome = ReconciliationOutcome(
            chosen_verdict=majority,
            primary_confidence=primary.confidence,
            secondary_confidence=secondary.confidence,
            third_invoked=True,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            reason="majority_vote",
        )
        self._emit(outcome)
        return outcome

    async def _invoke_third(
        self,
        *,
        target_agent_id: str,
        intent: "IntentMessage",
        claimed: "IntentResult",
        exclude_ids: set[str],
    ) -> TwoStageOutcome | None:
        """Pick a third red-team agent at random (excluding primary/secondary)
        and run a TwoStageVerifier-wrapped verification on it.
        """
        agents = [
            a for a in (getattr(self._runtime, "red_team_agents", None) or [])
            if getattr(a, "id", None) not in exclude_ids
        ]
        if not agents:
            return None
        third = random.choice(agents)
        verifier = TwoStageVerifier(
            red_team=third,
            emit_event=self._emit_event,
            metadata_threshold=self._metadata_threshold,
        )
        try:
            return await verifier.verify(
                target_agent_id=target_agent_id,
                intent=intent,
                claimed=claimed,
            )
        except Exception:
            logger.warning(
                "AD-451: third-verifier invocation failed (target=%s, intent=%s)",
                target_agent_id, intent.id, exc_info=True,
            )
            return None

    def _emit(self, outcome: ReconciliationOutcome) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.VALIDATION_RECONCILIATION_REQUESTED,
                {
                    "chosen_verdict": outcome.chosen_verdict,
                    "primary_confidence": outcome.primary_confidence,
                    "secondary_confidence": outcome.secondary_confidence,
                    "third_invoked": outcome.third_invoked,
                    "target_agent_id": outcome.target_agent_id,
                    "intent_id": outcome.intent_id,
                    "reason": outcome.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-451: VALIDATION_RECONCILIATION_REQUESTED emit failed "
                "(target=%s, intent=%s)",
                outcome.target_agent_id, outcome.intent_id, exc_info=True,
            )
