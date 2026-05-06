"""AD-633f / AD-633g: Protocol seams for idle-cycle speculation and preplay.

Both Protocols ship with NoOp default implementations in v1. Concrete impls
follow when consumer signals arrive (see module forcing functions):

- AD-633f-1: Concrete IdleSpeculationPolicy lands once AD-633e accuracy data
  shows >= 10% hit rate from operational predictions, justifying the energy
  cost of idle-cycle speculation.
- AD-633g-1: Concrete PreplayHook + dream Step 13 wiring lands once the dream
  pipeline exposes a step registry (today only ``on_pre_dream`` /
  ``on_post_dream`` / ``on_post_micro_dream`` are extension points).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from probos.cognitive.predictive_branching.executor import SpeculationRequest


@runtime_checkable
class IdleSpeculationPolicy(Protocol):
    """AD-633f: Decides whether to dispatch anticipatory speculation during idle cycles."""

    def should_speculate_now(
        self, *, agent_id: str, runtime: Any
    ) -> SpeculationRequest | None:
        """Return a SpeculationRequest to dispatch, or None to skip this cycle."""
        ...


@runtime_checkable
class PreplayHook(Protocol):
    """AD-633g: Generates forward-simulation predictions during dream consolidation."""

    def generate_preplay_predictions(
        self, *, dream_report: Any, runtime: Any
    ) -> list[SpeculationRequest]:
        """Return a list of SpeculationRequests to dispatch as preplay rollouts."""
        ...


class NoOpIdleSpeculationPolicy:
    """AD-633f v1 default. Always returns None. Stable until AD-633f-1."""

    def should_speculate_now(
        self, *, agent_id: str, runtime: Any
    ) -> SpeculationRequest | None:
        return None


class NoOpPreplayHook:
    """AD-633g v1 default. Always returns []. Stable until AD-633g-1."""

    def generate_preplay_predictions(
        self, *, dream_report: Any, runtime: Any
    ) -> list[SpeculationRequest]:
        return []
