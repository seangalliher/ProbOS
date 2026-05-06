"""Capability confidence scorer (AD-512e v1).

Per-agent per-capability calibrated confidence using a Beta(α, β) update.
**Stores raw (alpha, beta) parameters per the ProbOS standing-order
trust principle** — never derived means.

The mean confidence is α / (α + β); the variance is the calibration
signal ("how confident is the confidence"). v1 ships scoring only —
the eventual AD-486 Holodeck consumer feeds outcomes through
``record_attempt(agent_id, capability, success)`` and queries
``get_confidence`` / ``get_calibration``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityConfidence:
    """Per-(agent, capability) Beta(α, β) raw parameters.

    Mean confidence = alpha / (alpha + beta).
    Variance       = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1)).
    """

    agent_id: str
    capability_category: str
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        denom = self.alpha + self.beta
        if denom <= 0.0:
            return 0.0
        return self.alpha / denom

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        denom = (a + b) ** 2 * (a + b + 1)
        if denom <= 0.0:
            return 0.0
        return (a * b) / denom


class CapabilityConfidenceScorer:
    """Beta(α, β) accumulator, per-agent per-capability. AD-512e v1.

    Public API:
        record_attempt(agent_id, capability, success) -> CapabilityConfidence
        get_confidence(agent_id, capability) -> CapabilityConfidence
        list_for_agent(agent_id) -> tuple[CapabilityConfidence, ...]
        reset(agent_id, capability) -> None
    """

    def __init__(
        self,
        *,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        if prior_alpha <= 0.0 or prior_beta <= 0.0:
            raise ValueError("prior_alpha and prior_beta must be > 0")
        self._prior_alpha = prior_alpha
        self._prior_beta = prior_beta
        # key: (agent_id, capability_category) -> (alpha, beta)
        self._params: dict[tuple[str, str], tuple[float, float]] = {}
        self.emit_event: Callable[..., None] | None = None

    def record_attempt(
        self,
        agent_id: str,
        capability_category: str,
        success: bool,
    ) -> CapabilityConfidence:
        """Increment α on success, β on failure. Returns updated confidence."""
        key = (agent_id, capability_category)
        a, b = self._params.get(key, (self._prior_alpha, self._prior_beta))
        if success:
            a += 1.0
        else:
            b += 1.0
        self._params[key] = (a, b)
        conf = CapabilityConfidence(
            agent_id=agent_id,
            capability_category=capability_category,
            alpha=a,
            beta=b,
        )
        self._emit_updated(conf)
        return conf

    def get_confidence(
        self,
        agent_id: str,
        capability_category: str,
    ) -> CapabilityConfidence:
        """Return current confidence (prior if no attempts recorded)."""
        key = (agent_id, capability_category)
        a, b = self._params.get(key, (self._prior_alpha, self._prior_beta))
        return CapabilityConfidence(
            agent_id=agent_id,
            capability_category=capability_category,
            alpha=a,
            beta=b,
        )

    def list_for_agent(self, agent_id: str) -> tuple[CapabilityConfidence, ...]:
        out: list[CapabilityConfidence] = []
        for (aid, cat), (a, b) in self._params.items():
            if aid != agent_id:
                continue
            out.append(CapabilityConfidence(
                agent_id=aid, capability_category=cat, alpha=a, beta=b,
            ))
        return tuple(out)

    def reset(self, agent_id: str, capability_category: str) -> None:
        """Drop the (agent, capability) record. Caller decides when."""
        self._params.pop((agent_id, capability_category), None)

    def _emit_updated(self, conf: CapabilityConfidence) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.CAPABILITY_CONFIDENCE_UPDATED,
                {
                    "agent_id": conf.agent_id,
                    "capability_category": conf.capability_category,
                    "alpha": conf.alpha,
                    "beta": conf.beta,
                    "mean": conf.mean,
                    "variance": conf.variance,
                },
            )
        except Exception:
            logger.warning(
                "AD-512e: emit_event failed for agent_id=%s; continuing",
                conf.agent_id,
                exc_info=True,
            )
