"""AD-463: ModelRouter -- model selection given (tier, cost_ceiling) + policy.

v1 logic:
  1. Pull all available models in the requested tier from ModelRegistry.
  2. Apply the cost ceiling: the operator's, handed in at construction
     (BF-886), tightened by an optional per-call ceiling.
  3. If the ceiling leaves the tier no admissible model -- every available
     model in it is priced above the ceiling or unpriced, or (BF-886 A-1)
     the tier has none and no other tier offers one within the ceiling --
     emit MODEL_FALLBACK and choose no model, flagged
     ``excluded_by_cost_ceiling``: the caller treats the tier attempt as
     unavailable and sends nothing for it (BF-886).
  4. If the tier has no available model, emit MODEL_FALLBACK with reason;
     pick the first available model within the ceiling from any tier (as a
     last-resort fallback), or none.
  5. Emit MODEL_ROUTED with the chosen model name.

Unknown prices (BF-886 A-1): a price of 0.0 is the descriptor's "unknown or
free" convention. With a ceiling configured, a model needs a known output
price at or under it, so an unpriced model fails every ceiling, as #1474
requires; ``report_cost_ceiling`` logs an ERROR naming each tier left without
an admissible model and the remedy. Without a ceiling nothing is filtered.

``preview`` and ``denials`` give the same decision as ``choose`` without
logging or events, so a connectivity probe -- itself a generation request --
obeys the policy a completion does. ``build_model_routing`` builds the router
the same way for the boot factory, startup wiring and ``probos doctor``.

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
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.cognitive.model_registry import ModelDescriptor, ModelRegistry, catalog
from probos.events import EventType

if TYPE_CHECKING:
    from probos.config import SystemConfig

logger = logging.getLogger(__name__)

# BF-886: distinct (tier, model, reason) reports remembered before the memory
# resets, which bounds it if callers vary their per-call ceilings.
_REPORTED_LIMIT = 256
# BF-886 A-1: what follows a decision that leaves the tier without a model.
_SKIPPED = "the tier attempt is skipped and the caller's tier fallback chain continues"


@dataclass(frozen=True)
class RoutingDecision:
    """Outcome of one routing call."""

    chosen_model: str
    requested_tier: str
    reason: str
    fallback: bool = False
    # BF-886: the cost ceiling leaves the tier no admissible model.
    # ``chosen_model`` is then "", and the caller must treat the tier attempt
    # as unavailable rather than send any model for it.
    excluded_by_cost_ceiling: bool = False
    # AD-1324: the stakes floor leaves the tier no admissible model. Mirrors
    # ``excluded_by_cost_ceiling``: ``chosen_model`` is "" and the caller must not
    # send any model for the attempt.
    excluded_by_floor: bool = False
    # AD-1324: the tier of the chosen model ("" when none); excluded from equality
    # so a decision compares as it did before this field existed.
    chosen_tier: str = field(default="", compare=False)
    # AD-1324 amendment 1: an exact-tier request found no model registered for ITS tier. The any-tier
    # fallback is not taken; ``chosen_model`` is "" and the caller must not send any model.
    excluded_exact: bool = field(default=False, compare=False)


def _tier_rank(tier: str) -> int:
    """AD-1324: rank of a text tier (higher = more capable); -1 for any other tier."""
    from probos.cognitive.llm_client import TEXT_TIERS

    try:
        return TEXT_TIERS.index(tier)
    except ValueError:
        return -1


def _meets_floor(descriptor_tier: str, min_tier: str | None) -> bool:
    """AD-1324: whether a model registered at ``descriptor_tier`` satisfies ``min_tier``."""
    if min_tier is None:
        return True
    return _tier_rank(descriptor_tier) >= _tier_rank(min_tier) >= 0


def _within_ceiling(descriptor: ModelDescriptor, ceiling: float | None) -> bool:
    """BF-886: whether ``descriptor`` may be chosen under ``ceiling``.

    With a ceiling, a model needs a known output price at or under it; an
    unknown price (0.0) fails (A-1, #1474).
    """
    if ceiling is None:
        return True
    price = descriptor.cost_per_million_output_tokens
    return 0.0 < price <= ceiling


def _priced(descriptors: Iterable[ModelDescriptor]) -> str:
    return ", ".join(
        f"{d.name} at {d.cost_per_million_output_tokens:.2f}"
        if d.cost_per_million_output_tokens > 0.0
        else f"{d.name} with no known price"
        for d in descriptors
    )


class ModelRouter:
    """Composes ModelRegistry into selection.

    Stateless apart from log de-duplication: each ``choose()`` call queries
    the registry and returns a fresh ``RoutingDecision``.

    v1 policy: cost-aware (cheapest by output cost) + availability-aware
    (skip unavailable models) + cost-ceiling filter (operator-configurable,
    applied on every call since BF-886). Per-agent routing bias deferred to
    AD-463d.
    """

    def __init__(
        self,
        *,
        registry: "ModelRegistry",
        emit_event: Any | None = None,
        cost_ceiling: float | None = None,
    ) -> None:
        self._registry = registry
        self._emit_event = emit_event
        self._cost_ceiling = cost_ceiling
        self._reported: set[tuple[str, str, str]] = set()

    @property
    def cost_ceiling(self) -> float | None:
        """BF-886: the operator's ceiling in USD per million output tokens, or None."""
        return self._cost_ceiling

    @property
    def registry(self) -> ModelRegistry:
        """BF-886 A-1: the registry this router chooses from."""
        return self._registry

    def choose(
        self,
        *,
        tier: str,
        cost_ceiling: float | None = None,
        min_tier: str | None = None,
        correlation: dict[str, Any] | None = None,
        exact_tier: bool = False,
    ) -> RoutingDecision:
        decision, next_step = self._decide(
            tier, self._effective_ceiling(cost_ceiling), min_tier=min_tier, exact_tier=exact_tier,
        )
        if next_step:
            self._report(decision, next_step)
        extra = _correlation_payload(correlation, decision, min_tier)
        if decision.fallback:
            self._emit_fallback(decision, extra)
        else:
            self._emit_routed(decision, extra)
        return decision

    def preview(self, *, tier: str, min_tier: str | None = None, exact_tier: bool = False) -> RoutingDecision:
        """BF-886 A-1: the decision ``choose`` makes under the configured ceiling.

        Logs nothing and emits no event, so a connectivity probe can ask which
        model it may send -- and whether it may send any -- before it does.
        """
        decision, _ = self._decide(tier, self._cost_ceiling, min_tier=min_tier, exact_tier=exact_tier)
        return decision

    def denials(self, tiers: Iterable[str]) -> dict[str, str]:
        """BF-886 A-1: ``{tier: reason}`` for each tier the configured ceiling leaves no model.

        Logs nothing and emits no event; ``{}`` when no ceiling is configured.
        """
        denied: dict[str, str] = {}
        for tier in tiers:
            decision = self.preview(tier=tier)
            if decision.excluded_by_cost_ceiling:
                denied[tier] = decision.reason
        return denied

    def report_cost_ceiling(self, tiers: Iterable[str]) -> dict[str, str]:
        """BF-886: log, once at wiring, how the configured ceiling treats each tier.

        Returns ``{tier: status}``, or ``{}`` when no ceiling is configured
        (routing is then unchanged and nothing is logged). Status is one of:

        - ``"excluded"``: the tier has available models and the ceiling
          admits none of them -- each is priced above it or has no known
          price (A-1). Logged at ERROR, naming the models, the ceiling and
          the remedy: each call skips the tier along its fallback chain, and
          a call with no tier left fails naming the ceiling.
        - ``"within"``: the tier has a model priced at or under the ceiling.
        - ``"empty"``: the tier has no available model; nothing is logged.
        """
        ceiling = self._cost_ceiling
        if ceiling is None:
            return {}
        fits = [d for d in catalog() if _within_ceiling(d, ceiling)]
        remedy = (
            "configure a model the built-in catalog prices at or under the ceiling "
            f"({_priced(fits)}), or unset the ceiling (raising it admits only a model with a known price)"
            if fits
            else "no model in the built-in catalog fits this ceiling: raise it until one does and configure that model, or unset it"
        )
        report: dict[str, str] = {}
        for tier in tiers:
            available = self._registry.by_tier(tier)
            if not available:
                report[tier] = "empty"
            elif any(_within_ceiling(d, ceiling) for d in available):
                report[tier] = "within"
            else:
                report[tier] = "excluded"
                logger.error(
                    "BF-886: model routing cost ceiling %.2f USD per million output "
                    "tokens leaves tier %s with no admissible model (%s); every call "
                    "on that tier is refused and falls back along the tier chain, and "
                    "a call with no tier left fails naming the ceiling -- %s "
                    "(model_routing.cost_ceiling_per_million_output_tokens)",
                    ceiling, tier, _priced(available), remedy,
                )
        return report

    def _decide(
        self, tier: str, ceiling: float | None, *, min_tier: str | None = None, exact_tier: bool = False,
    ) -> tuple[RoutingDecision, str]:
        """The decision for ``tier`` under ``ceiling``, and what follows it.

        The second item is the next step a report should name, or "" for the
        tier's single registered model, which is not reported.
        """
        available = self._registry.by_tier(tier)
        if min_tier is not None and not _meets_floor(tier, min_tier):
            # AD-1324: the floor only removes candidates; a requested tier below it
            # has none, and no other tier's model is substituted for it here.
            return RoutingDecision(
                chosen_model="",
                requested_tier=tier,
                reason=f"stakes floor '{min_tier}' excludes tier '{tier}'",
                fallback=True,
                excluded_by_floor=True,
            ), _SKIPPED
        candidates = [d for d in available if _within_ceiling(d, ceiling)]

        if available and not candidates:
            return RoutingDecision(
                chosen_model="",
                requested_tier=tier,
                reason=(
                    f"cost ceiling {ceiling:.2f} USD per million output tokens "
                    f"excludes every available model in tier '{tier}' "
                    f"({_priced(available)})"
                ),
                fallback=True,
                excluded_by_cost_ceiling=True,
            ), _SKIPPED

        if not candidates and exact_tier:
            return RoutingDecision(
                chosen_model="",
                requested_tier=tier,
                reason=f"no available model registered for tier '{tier}' (exact tier requested)",
                fallback=True,
                excluded_exact=True,
            ), _SKIPPED

        if not candidates:
            # No available model in the tier -- emit fallback
            for d in self._registry.all():
                if d.available and _within_ceiling(d, ceiling) and _meets_floor(d.tier, min_tier):
                    return RoutingDecision(
                        chosen_model=d.name,
                        requested_tier=tier,
                        reason=f"no available models in tier '{tier}' (cost_ceiling={ceiling})",
                        fallback=True,
                        chosen_tier=d.tier,
                    ), f"the request goes out as {d.name}, registered for tier '{d.tier}'"
            if min_tier is not None:
                return RoutingDecision(
                    chosen_model="",
                    requested_tier=tier,
                    reason=f"no available model at or above stakes floor '{min_tier}'",
                    fallback=True,
                    excluded_by_floor=True,
                ), _SKIPPED
            if ceiling is None:
                return RoutingDecision(
                    chosen_model="",
                    requested_tier=tier,
                    reason="no available models in any tier",
                    fallback=True,
                ), "the caller sends the tier's configured model unrouted"
            # BF-886 A-1: under a ceiling, no admissible model anywhere is a
            # denial -- never a licence to send the configured model unchecked.
            return RoutingDecision(
                chosen_model="",
                requested_tier=tier,
                reason=f"no available model within cost ceiling {ceiling:.2f} in any tier",
                fallback=True,
                excluded_by_cost_ceiling=True,
            ), _SKIPPED

        # Single-candidate fast path
        if len(candidates) == 1:
            return RoutingDecision(
                chosen_model=candidates[0].name,
                requested_tier=tier,
                reason="single candidate",
                chosen_tier=candidates[0].tier,
            ), ""

        # Multi-candidate: cheapest by output cost, tiebreak by name (v1 default).
        # AD-463d will add per-agent routing bias via HebbianRouter integration
        # once LLMRequest carries agent context.
        chosen = min(
            candidates,
            key=lambda d: (d.cost_per_million_output_tokens, d.name),
        )
        return RoutingDecision(
            chosen_model=chosen.name,
            requested_tier=tier,
            reason="cheapest-by-output-cost",
            chosen_tier=chosen.tier,
        ), (
            f"the request goes out as {chosen.name}, chosen among "
            f"{len(candidates)} registered candidates"
        )

    def _effective_ceiling(self, call_ceiling: float | None) -> float | None:
        """BF-886: a per-call ceiling can tighten the operator's, never lift it."""
        if self._cost_ceiling is None:
            return call_ceiling
        if call_ceiling is None:
            return self._cost_ceiling
        return min(self._cost_ceiling, call_ceiling)

    def _report(self, decision: RoutingDecision, next_step: str) -> None:
        """BF-886: log a choice other than a tier's single registered model.

        The first report of each (tier, model, reason) logs at WARNING for a
        fallback and INFO otherwise; repeats log at DEBUG.
        """
        key = (decision.requested_tier, decision.chosen_model, decision.reason)
        if key in self._reported:
            level = logging.DEBUG
        else:
            if len(self._reported) >= _REPORTED_LIMIT:
                self._reported.clear()
            self._reported.add(key)
            level = logging.WARNING if decision.fallback else logging.INFO
        logger.log(
            level,
            "AD-463: model routing for tier %s chose %s: %s; %s",
            decision.requested_tier,
            decision.chosen_model or "no model",
            decision.reason,
            next_step,
        )

    def _emit_routed(self, decision: RoutingDecision, extra: dict[str, Any] | None = None) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.MODEL_ROUTED,
                {
                    "chosen_model": decision.chosen_model,
                    "tier": decision.requested_tier,
                    "reason": decision.reason,
                    **(extra or {}),
                },
            )
        except Exception:
            logger.warning(
                "AD-463: MODEL_ROUTED emit failed (model=%s, tier=%s)",
                decision.chosen_model, decision.requested_tier, exc_info=True,
            )

    def _emit_fallback(self, decision: RoutingDecision, extra: dict[str, Any] | None = None) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.MODEL_FALLBACK,
                {
                    "chosen_model": decision.chosen_model,
                    "tier": decision.requested_tier,
                    "reason": decision.reason,
                    **(extra or {}),
                },
            )
        except Exception:
            logger.warning(
                "AD-463: MODEL_FALLBACK emit failed (model=%s, tier=%s)",
                decision.chosen_model, decision.requested_tier, exc_info=True,
            )


# AD-1324: the additive, armed-only keys a routing event may carry.
_CORRELATION_KEYS = ("request_id", "agent_id", "work_item_id", "tier_reason")


def _correlation_payload(
    correlation: dict[str, Any] | None, decision: RoutingDecision, min_tier: str | None,
) -> dict[str, Any]:
    """AD-1324: extra routing-event keys; ``{}`` unless the caller armed correlation."""
    if not correlation:
        return {}
    extra: dict[str, Any] = {
        key: correlation[key]
        for key in _CORRELATION_KEYS
        if type(correlation.get(key)) is str and correlation[key]
    }
    extra["requested_tier"] = decision.requested_tier
    if decision.chosen_tier:
        extra["chosen_tier"] = decision.chosen_tier
    if min_tier is not None:
        extra["min_tier"] = min_tier
    return extra


def build_model_routing(
    config: SystemConfig, *, emit_event: Any | None = None,
) -> ModelRouter | None:
    """BF-886 A-1: the model router ``config`` describes, or None when routing is off.

    Its registry holds exactly the configured model of each text tier
    (``ModelRegistry.from_tier_models``), and it applies the configured cost
    ceiling. The boot factory, startup wiring and ``probos doctor`` all build
    it here, so a probe obeys the policy a completion does.
    """
    if not config.model_routing.enabled:
        return None
    from probos.cognitive.llm_client import TEXT_TIERS

    registry = ModelRegistry.from_tier_models(
        {tier: config.cognitive.tier_config(tier)["model"] for tier in TEXT_TIERS},
    )
    return ModelRouter(
        registry=registry,
        emit_event=emit_event,
        cost_ceiling=config.model_routing.cost_ceiling_per_million_output_tokens,
    )


def ceiling_denials(config: SystemConfig) -> dict[str, str]:
    """BF-886 A-1: ``{tier: reason}`` for each text tier ``config``'s cost ceiling leaves no model.

    ``{}`` when routing is off or no ceiling is set. Nothing may send a
    generation request -- a completion, a probe or a warm-up -- for these.
    """
    router = build_model_routing(config)
    if router is None:
        return {}
    from probos.cognitive.llm_client import TEXT_TIERS

    return router.denials(TEXT_TIERS)
