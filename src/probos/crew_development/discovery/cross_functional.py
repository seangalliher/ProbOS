"""Cross-functional Hebbian-routing suggestion (AD-512c v1).

Translates a discovery struggle into a *suggestion* of a Hebbian edge
that the eventual AD-486 Holodeck consumer can write via
``runtime.hebbian_router.record_interaction(...)``. v1 produces the
tuple shape only; **no Hebbian writes happen inside this module**.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos.crew_development.discovery.strength_map import StrengthRecord


@dataclass(frozen=True)
class CrossFunctionalSuggestion:
    """A suggested Hebbian edge derived from a discovery outcome.

    Caller is responsible for invoking
    ``runtime.hebbian_router.record_interaction(source, target, success, rel_type)``
    (mesh.routing:177) when the design says the suggestion should be acted on.
    """

    source: str            # struggling agent_id
    target: str            # peer-expert agent_id whose strength matches
    success: bool          # True if suggesting to STRENGTHEN (peer succeeded
                           # where source struggled); False to weaken
    rel_type: str          # always "agent" — peer-relationship edge
    rationale: str         # short human-readable explanation


def suggest_routing(
    *,
    struggling_record: StrengthRecord,
    peer_expert_id: str,
) -> CrossFunctionalSuggestion:
    """Translate a struggle + a peer-expert id into a routing suggestion.

    Caller responsibilities (kept out of v1 to preserve substrate purity):
        1. Identify the peer expert (typically via
           ``StrengthMap.get_strengths(peer_id) ∩ struggling_record.capability_category``).
        2. Decide whether to write the edge by calling
           ``runtime.hebbian_router.record_interaction(...)``.
        3. Optionally emit a domain event after the write.

    The suggestion's ``success`` field is True when the source struggled
    (``not struggling_record.success``) — strengthening the edge to the
    peer-expert. If the source actually succeeded, ``success`` is False
    (no need to strengthen).
    """
    is_struggle = not struggling_record.success
    rationale = (
        f"{struggling_record.agent_id} struggled with "
        f"{struggling_record.capability_category} "
        f"(scenario {struggling_record.scenario_id}); "
        f"{peer_expert_id} is a peer expert."
    )
    return CrossFunctionalSuggestion(
        source=struggling_record.agent_id,
        target=peer_expert_id,
        success=is_struggle,
        rel_type="agent",
        rationale=rationale,
    )
