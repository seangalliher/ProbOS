"""AD-633b: Speculation Executor — wraps SubTaskExecutor with speculation accounting.

Speculative chains are tagged ``source="speculation"`` so AD-632 token
attribution can route them to the speculation budget pool. Emits
PREDICTION_ERROR_RECORDED (AD-633h) when a previously-cached prediction is
later observed to diverge from the agent's actual decision.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.cognitive.predictive_branching.engine import PredictionDescriptor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeculationRequest:
    """AD-633b/f: Request for the executor to dispatch a speculative chain.

    Used both by the operational path (engine -> executor) and by the future
    AD-633f IdleSpeculationPolicy + AD-633g PreplayHook surfaces.
    """

    descriptor: PredictionDescriptor
    chain: Any  # SubTaskChain — Any to avoid hard import (AD-632 may be disabled)
    requested_at: float = field(default_factory=time.time)
    origin: str = "operational"  # "operational" | "anticipatory" | "preplay"


class SpeculationExecutor:
    """AD-633b: Dispatches speculative SubTaskChains and records outcomes.

    Constructor injection. ``sub_task_executor`` may be None — in that case
    ``dispatch()`` returns None and the caller falls back to operational LLM.
    """

    def __init__(
        self,
        *,
        sub_task_executor: Any,
        cache: Any,
        budget: Any,
        accuracy_tracker: Any,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._executor = sub_task_executor
        self._cache = cache
        self._budget = budget
        self._accuracy = accuracy_tracker
        self._emit = emit_event

    async def dispatch(
        self,
        request: SpeculationRequest,
        *,
        context: dict[str, Any] | None = None,
        agency_level: str | None = None,
    ) -> dict[str, Any] | None:
        """Dispatch a speculative chain and store the result in the cache.

        Returns the stored payload (also written to cache) or None if dispatch
        was skipped (executor unavailable, budget exhausted, agency gate).
        Tier-2 log-and-degrade everywhere.
        """
        if self._executor is None:
            return None

        # Budget gate
        try:
            tokens_estimate = self._estimate_tokens(request.chain)
            if not self._budget.try_reserve(
                agent_id=request.descriptor.agent_id,
                tokens=tokens_estimate,
                tier=request.descriptor.tier,
                agency_level=agency_level,
            ):
                logger.debug(
                    "AD-633c: speculation budget exhausted for %s; skipping",
                    request.descriptor.agent_id,
                )
                return None
        except Exception:
            logger.warning(
                "AD-633c: budget reserve failed; skipping speculation", exc_info=True
            )
            return None

        try:
            results = await self._executor.execute(request.chain, context or {})
        except Exception:
            logger.warning(
                "AD-633b: speculative chain execute failed for %s; skipping",
                request.descriptor.agent_id, exc_info=True,
            )
            return None

        actual_tokens = self._sum_tokens(results)
        try:
            self._budget.record_consumption(
                agent_id=request.descriptor.agent_id, tokens=actual_tokens
            )
        except Exception:
            logger.warning("AD-633c: record_consumption failed", exc_info=True)

        payload = {
            "descriptor": request.descriptor,
            "results": results,
            "origin": request.origin,
            "tokens_used": actual_tokens,
        }
        try:
            self._cache.store(
                signature=request.descriptor.signature,
                agent_id=request.descriptor.agent_id,
                intent_type=request.descriptor.intent_type,
                payload=payload,
            )
        except Exception:
            logger.warning("AD-633b: cache store failed", exc_info=True)

        return payload

    async def dispatch_anticipatory(
        self, request: SpeculationRequest, *, agency_level: str | None = None
    ) -> dict[str, Any] | None:
        """AD-633f future entry point. Same semantics as ``dispatch`` with
        ``origin='anticipatory'`` already baked into the request."""
        return await self.dispatch(request, agency_level=agency_level)

    def record_outcome(
        self,
        *,
        descriptor: PredictionDescriptor,
        actual_intent: str,
        actual_decision_summary: str,
    ) -> None:
        """AD-633e/h: After the agent actually decides, compare to prediction.

        - Predicted intent matches actual intent -> ``HIT`` (already counted on lookup)
        - Predicted intent did NOT match actual intent -> ``ERROR`` and emit
          PREDICTION_ERROR_RECORDED for AD-557 (event-emit only at HEAD).
        """
        from probos.cognitive.predictive_branching.accuracy import PredictionOutcome

        try:
            if descriptor.intent_type and descriptor.intent_type == actual_intent:
                self._accuracy.record(
                    agent_id=descriptor.agent_id, outcome=PredictionOutcome.HIT
                )
                return
            self._accuracy.record(
                agent_id=descriptor.agent_id, outcome=PredictionOutcome.ERROR
            )
            if self._emit is not None:
                self._emit(
                    "prediction_error_recorded",
                    {
                        "agent_id": descriptor.agent_id,
                        "predicted_intent": descriptor.intent_type,
                        "actual_intent": actual_intent,
                        "confidence": descriptor.confidence,
                        "tier": descriptor.tier.value,
                    },
                )
        except Exception:
            logger.warning(
                "AD-633h: record_outcome failed for %s; continuing",
                descriptor.agent_id, exc_info=True,
            )

    @staticmethod
    def _estimate_tokens(chain: Any) -> int:
        """Rough estimate from prompt template lengths. Falls back to 500 on shape mismatch."""
        try:
            steps = getattr(chain, "steps", []) or []
            total = 0
            for step in steps:
                template = getattr(step, "prompt_template", "") or ""
                total += max(50, len(template) // 4)
            return max(50, total)
        except Exception:
            logger.warning(
                "AD-633b: _estimate_tokens shape mismatch on chain %r; using 500-token fallback",
                chain, exc_info=True,
            )
            return 500

    @staticmethod
    def _sum_tokens(results: Any) -> int:
        """Sum tokens_used across SubTaskResult list. Falls back to 0 on shape mismatch."""
        try:
            if not results:
                return 0
            return sum(int(getattr(r, "tokens_used", 0) or 0) for r in results)
        except Exception:
            logger.warning(
                "AD-633b: _sum_tokens shape mismatch on results; using 0-token fallback",
                exc_info=True,
            )
            return 0
