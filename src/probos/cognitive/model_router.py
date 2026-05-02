"""AD-463: ModelRouter -- model selection given (tier, cost_ceiling) + policy.

v1 logic:
  1. Pull all available models in the requested tier from ModelRegistry.
  2. Apply optional cost_ceiling filter.
  3. If no candidates remain, emit MODEL_FALLBACK with reason; pick the
     first available model from any tier (as a last-resort fallback).
  4. Emit MODEL_ROUTED with the chosen model name.

HebbianRouter integration is **deferred wholesale to AD-463d**. Pass-1
review caught that the original draft consulted HebbianRouter via an
``agent_id`` parameter that LLMRequest does not carry today; the integration
would have been dead code (theater). v1 ModelRouter is cost-aware and
availability-aware; AD-463d will introduce the per-agent routing seam
once ``LLMRequest.agent_id`` (or an equivalent context-passing mechanism)
is established.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.model_registry import ModelRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingDecision:
    """Outcome of one routing call."""

    chosen_model: str
    requested_tier: str
    reason: str
    fallback: bool = False


class ModelRouter:
    """Composes ModelRegistry into selection.

    Stateless. Each ``choose()`` call queries the registry and returns a
    fresh ``RoutingDecision``.

    v1 policy: cost-aware (cheapest by output cost) + availability-aware
    (skip unavailable models) + cost-ceiling filter (operator-configurable).
    Per-agent routing bias deferred to AD-463d.
    """

    def __init__(
        self,
        *,
        registry: "ModelRegistry",
        emit_event: Any | None = None,
    ) -> None:
        self._registry = registry
        self._emit_event = emit_event

    def choose(
        self,
        *,
        tier: str,
        cost_ceiling: float | None = None,
    ) -> RoutingDecision:
        candidates = self._registry.by_tier(tier)
        if cost_ceiling is not None:
            candidates = [
                d for d in candidates
                if d.cost_per_million_output_tokens <= cost_ceiling
            ]

        if not candidates:
            # No candidates in tier (or under cost ceiling) -- emit fallback
            for d in self._registry.all():
                if d.available:
                    decision = RoutingDecision(
                        chosen_model=d.name,
                        requested_tier=tier,
                        reason=f"no available models in tier '{tier}' (cost_ceiling={cost_ceiling})",
                        fallback=True,
                    )
                    self._emit_fallback(decision)
                    return decision
            decision = RoutingDecision(
                chosen_model="",
                requested_tier=tier,
                reason="no available models in any tier",
                fallback=True,
            )
            self._emit_fallback(decision)
            return decision

        # Single-candidate fast path
        if len(candidates) == 1:
            chosen = candidates[0]
            decision = RoutingDecision(
                chosen_model=chosen.name,
                requested_tier=tier,
                reason="single candidate",
            )
            self._emit_routed(decision)
            return decision

        # Multi-candidate: cheapest by output cost, tiebreak by name (v1 default).
        # AD-463d will add per-agent routing bias via HebbianRouter integration
        # once LLMRequest carries agent context.
        chosen = min(
            candidates,
            key=lambda d: (d.cost_per_million_output_tokens, d.name),
        )
        decision = RoutingDecision(
            chosen_model=chosen.name,
            requested_tier=tier,
            reason="cheapest-by-output-cost",
        )
        self._emit_routed(decision)
        return decision

    def _emit_routed(self, decision: RoutingDecision) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.MODEL_ROUTED,
                {
                    "chosen_model": decision.chosen_model,
                    "tier": decision.requested_tier,
                    "reason": decision.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-463: MODEL_ROUTED emit failed (model=%s, tier=%s)",
                decision.chosen_model, decision.requested_tier, exc_info=True,
            )

    def _emit_fallback(self, decision: RoutingDecision) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.MODEL_FALLBACK,
                {
                    "chosen_model": decision.chosen_model,
                    "tier": decision.requested_tier,
                    "reason": decision.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-463: MODEL_FALLBACK emit failed (model=%s, tier=%s)",
                decision.chosen_model, decision.requested_tier, exc_info=True,
            )
