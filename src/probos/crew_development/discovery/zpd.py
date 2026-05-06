"""Vygotsky Zone of Proximal Development calibrator (AD-512f v1).

Selects discovery scenarios calibrated to an agent's edge of current
ability — neither so easy that no learning occurs nor so hard that the
agent founders without scaffolding.

ZPD band is anchored on the agent's current confidence mean
(``CapabilityConfidence.mean``) and a configurable lower/upper offset.
Scenarios whose ``difficulty`` falls inside the band are returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.crew_development.discovery.confidence import CapabilityConfidence
from probos.crew_development.discovery.scenarios import DiscoveryScenario
from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZPDBand:
    """A difficulty band for an agent in a capability category. AD-512f v1.

    ``difficulty_low`` and ``difficulty_high`` are inclusive bounds on
    [0.0, 1.0]. ``scaffolding_hint`` is a string suggestion for the
    eventual presenter (``high`` / ``medium`` / ``low`` / ``none``).
    """

    agent_id: str
    capability_category: str
    confidence_mean: float
    difficulty_low: float
    difficulty_high: float
    scaffolding_hint: str


class ZPDCalibrator:
    """Selects scenarios within an agent's Zone of Proximal Development. AD-512f v1.

    Public API:
        compute_band(confidence, *, lower_offset, upper_offset) -> ZPDBand
        select_scenarios(confidence, scenarios, *, lower_offset, upper_offset)
            -> tuple[DiscoveryScenario, ...]
    """

    def __init__(
        self,
        *,
        lower_offset: float = 0.40,
        upper_offset: float = 0.75,
    ) -> None:
        if not 0.0 <= lower_offset < upper_offset <= 1.0:
            raise ValueError(
                "lower_offset must be in [0,1) and strictly less than upper_offset (which must be ≤ 1)"
            )
        self._lower_offset = lower_offset
        self._upper_offset = upper_offset
        self.emit_event: Callable[..., None] | None = None

    def compute_band(
        self,
        confidence: CapabilityConfidence,
        *,
        lower_offset: float | None = None,
        upper_offset: float | None = None,
    ) -> ZPDBand:
        """Compute the difficulty band relative to current confidence mean."""
        lo = lower_offset if lower_offset is not None else self._lower_offset
        hi = upper_offset if upper_offset is not None else self._upper_offset
        mean = confidence.mean
        # Difficulty band is anchored ABOVE current ability — Vygotsky:
        # the ZPD is what the learner can do with scaffolding, beyond
        # what they can do alone.
        difficulty_low = max(0.0, min(1.0, mean + (lo - 0.5)))
        difficulty_high = max(0.0, min(1.0, mean + (hi - 0.5)))
        # Lower mean → higher scaffolding need.
        if mean < 0.30:
            scaffolding_hint = "high"
        elif mean < 0.60:
            scaffolding_hint = "medium"
        elif mean < 0.85:
            scaffolding_hint = "low"
        else:
            scaffolding_hint = "none"
        band = ZPDBand(
            agent_id=confidence.agent_id,
            capability_category=confidence.capability_category,
            confidence_mean=mean,
            difficulty_low=difficulty_low,
            difficulty_high=difficulty_high,
            scaffolding_hint=scaffolding_hint,
        )
        self._emit_calibrated(band)
        return band

    def select_scenarios(
        self,
        confidence: CapabilityConfidence,
        scenarios: tuple[DiscoveryScenario, ...],
        *,
        lower_offset: float | None = None,
        upper_offset: float | None = None,
    ) -> tuple[DiscoveryScenario, ...]:
        """Filter scenarios to those within the agent's ZPD band.

        Filters by ``capability_category == confidence.capability_category``
        AND ``difficulty_low <= scenario.difficulty <= difficulty_high``.
        """
        band = self.compute_band(
            confidence,
            lower_offset=lower_offset,
            upper_offset=upper_offset,
        )
        out = tuple(
            s for s in scenarios
            if s.capability_category == confidence.capability_category
            and band.difficulty_low <= s.difficulty <= band.difficulty_high
        )
        return out

    def _emit_calibrated(self, band: ZPDBand) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.ZPD_SCENARIO_CALIBRATED,
                {
                    "agent_id": band.agent_id,
                    "capability_category": band.capability_category,
                    "confidence_mean": band.confidence_mean,
                    "difficulty_low": band.difficulty_low,
                    "difficulty_high": band.difficulty_high,
                    "scaffolding_hint": band.scaffolding_hint,
                },
            )
        except Exception:
            logger.warning(
                "AD-512f: emit_event failed for agent_id=%s; continuing",
                band.agent_id,
                exc_info=True,
            )
